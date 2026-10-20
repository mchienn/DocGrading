"""Process-local bounded LRU for normalized local-coherence embeddings."""

from collections import OrderedDict
from hashlib import sha256
from threading import Lock


class EmbeddingCache:
    def __init__(self, max_entries=2048, max_bytes=16 * 1024 * 1024):
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self._entries = OrderedDict()
        self._bytes = 0
        self._encoder = None
        self._config = None
        self._lock = Lock()

    def encode(self, texts, encoder):
        # Serialize misses so simultaneous requests never encode the same text twice.
        with self._lock:
            config = (
                getattr(encoder, "max_seq_length", None),
                str(getattr(encoder, "device", "")),
            )
            if self._encoder is not encoder or self._config != config:
                self._entries.clear()
                self._bytes = 0
                self._encoder, self._config = encoder, config
            unique = list(dict.fromkeys(texts))
            keys = {text: sha256(text.encode("utf-8")).digest() for text in unique}
            result, missing = {}, []
            for text, key in keys.items():
                if key in self._entries:
                    result[text] = self._entries[key]
                    self._entries.move_to_end(key)
                else:
                    missing.append(text)
            if missing:
                vectors = encoder.encode(
                    missing,
                    batch_size=64,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
                for text, vector in zip(missing, vectors, strict=True):
                    # Copy each row so one cache entry cannot retain a full batch.
                    vector = vector.copy()
                    result[text] = vector
                    size = vector.nbytes + len(keys[text])
                    if size > self.max_bytes or self.max_entries <= 0:
                        continue
                    while self._entries and (
                        len(self._entries) >= self.max_entries
                        or self._bytes + size > self.max_bytes
                    ):
                        old_key, old_vector = self._entries.popitem(last=False)
                        self._bytes -= old_vector.nbytes + len(old_key)
                    self._entries[keys[text]] = vector
                    self._bytes += size
            return result, len(missing)


local_embedding_cache = EmbeddingCache()
