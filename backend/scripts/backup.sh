#!/bin/sh
set -eu

umask 077
[ "${APP_ENV:-}" = "development" ] || {
    echo "Backup smoke is restricted to APP_ENV=development." >&2
    exit 1
}
backup_file=${BACKUP_FILE:-/backups/docgrading.dump}
counts_file=${COUNTS_FILE:-/backups/docgrading-row-counts.tsv}
backup_tmp="${backup_file}.tmp"
before_tmp="${counts_file}.before.tmp"
after_tmp="${counts_file}.after.tmp"
tables="users courses memberships course_invites assignments assignment_requirements rubric_versions criterion_versions template_versions submissions document_versions analysis_jobs analysis_job_dispatches document_irs findings evidence_anchors review_locks review_drafts review_decisions published_result_versions review_requests review_commands notifications sessions audit_events"

export PGPASSWORD=${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}
mkdir -p "$(dirname "$backup_file")" "$(dirname "$counts_file")"
trap 'rm -f "$backup_tmp" "$before_tmp" "$after_tmp"' EXIT

collect_counts() {
    output=$1
    : >"$output"
    for table in $tables; do
        count=$(psql -X -A -t --set=ON_ERROR_STOP=1 \
            --host="$POSTGRES_HOST" --port="${POSTGRES_PORT:-5432}" \
            --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" \
            --command="SELECT count(*) FROM public.$table")
        printf '%s\t%s\n' "$table" "$count" >>"$output"
    done
}

collect_counts "$before_tmp"
rm -f "$backup_tmp"
pg_dump --format=custom --no-owner --no-acl \
    --host="$POSTGRES_HOST" --port="${POSTGRES_PORT:-5432}" \
    --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" \
    --file="$backup_tmp"
collect_counts "$after_tmp"

if [ "$(cat "$before_tmp")" != "$(cat "$after_tmp")" ]; then
    echo "Backup aborted: row counts changed during pg_dump; quiesce writers and retry." >&2
    exit 1
fi

mv "$backup_tmp" "$backup_file"
mv "$before_tmp" "$counts_file"
rm -f "$after_tmp"
trap - EXIT

echo "Backup complete: $backup_file"
echo "Source row counts:"
cat "$counts_file"
