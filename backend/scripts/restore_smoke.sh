#!/bin/sh
set -eu
[ "${APP_ENV:-}" = "development" ] || {
    echo "Restore smoke is restricted to APP_ENV=development." >&2
    exit 1
}

backup_file=${BACKUP_FILE:-/backups/docgrading.dump}
counts_file=${COUNTS_FILE:-/backups/docgrading-row-counts.tsv}
restore_db=${RESTORE_DB:-docgrading_restore}

[ -s "$backup_file" ] || {
    echo "Backup file missing: $backup_file" >&2
    exit 1
}
[ -s "$counts_file" ] || {
    echo "Row-count file missing: $counts_file" >&2
    exit 1
}

export PGPASSWORD=${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}
connection="--host=$POSTGRES_HOST --port=${POSTGRES_PORT:-5432} --username=$POSTGRES_USER"

dropdb $connection --if-exists --force "$restore_db"
createdb $connection "$restore_db"
pg_restore $connection --exit-on-error --single-transaction --no-owner --no-acl \
    --dbname="$restore_db" "$backup_file"

echo "Restore target recreated clean: $restore_db"
echo "Restored row counts:"
while IFS="$(printf '\t')" read -r table expected; do
    case "$table" in
        *[!a-z0-9_]*)
            echo "Unsafe table name in count file: $table" >&2
            exit 1
            ;;
    esac
    actual=$(psql -X -A -t --set=ON_ERROR_STOP=1 $connection \
        --dbname="$restore_db" --command="SELECT count(*) FROM public.$table")
    printf '%s\t%s\n' "$table" "$actual"
    [ "$actual" = "$expected" ] || {
        echo "Row-count mismatch for $table: source=$expected restored=$actual" >&2
        exit 1
    }
done <"$counts_file"

critical_flow=$(psql -X -A -t --set=ON_ERROR_STOP=1 $connection \
    --dbname="$restore_db" --command="
        SELECT count(*)
        FROM public.published_result_versions result
        JOIN public.document_versions document
          ON document.id = result.document_version_id
        JOIN public.submissions submission
          ON submission.id = document.submission_id
        JOIN public.assignments assignment
          ON assignment.id = submission.assignment_id
        JOIN public.courses course
          ON course.id = assignment.course_id
        JOIN public.users student
          ON student.id = submission.student_id
        WHERE document.status = 'PUBLISHED'::public.document_status;")
[ "$critical_flow" -gt 0 ] || {
    echo "T-021 subset failed: no restored published critical-flow row" >&2
    exit 1
}

orphan_count=$(psql -X -A -t --set=ON_ERROR_STOP=1 $connection \
    --dbname="$restore_db" --command="
        SELECT
            (SELECT count(*) FROM public.memberships child
             LEFT JOIN public.courses parent ON parent.id = child.course_id
             LEFT JOIN public.users actor ON actor.id = child.user_id
             WHERE parent.id IS NULL OR actor.id IS NULL)
          + (SELECT count(*) FROM public.submissions child
             LEFT JOIN public.assignments parent ON parent.id = child.assignment_id
             LEFT JOIN public.users actor ON actor.id = child.student_id
             WHERE parent.id IS NULL OR actor.id IS NULL)
          + (SELECT count(*) FROM public.document_versions child
             LEFT JOIN public.submissions parent ON parent.id = child.submission_id
             WHERE parent.id IS NULL)
          + (SELECT count(*) FROM public.analysis_jobs child
             LEFT JOIN public.document_versions document
               ON document.id = child.document_version_id
             LEFT JOIN public.rubric_versions rubric
               ON rubric.id = child.rubric_version_id
             WHERE document.id IS NULL OR rubric.id IS NULL)
          + (SELECT count(*) FROM public.published_result_versions child
             LEFT JOIN public.document_versions parent
               ON parent.id = child.document_version_id
             WHERE parent.id IS NULL);")
[ "$orphan_count" = "0" ] || {
    echo "T-021 subset failed: restored relationship orphan count=$orphan_count" >&2
    exit 1
}

if truncate_output=$(psql -X --set=ON_ERROR_STOP=1 $connection \
    --dbname="$restore_db" --command="TRUNCATE public.audit_events" 2>&1); then
    echo "Audit TRUNCATE guard missing after restore" >&2
    exit 1
fi
case "$truncate_output" in
    *"audit events are append-only"*) ;;
    *)
        echo "Audit TRUNCATE failed for unexpected reason" >&2
        echo "$truncate_output" >&2
        exit 1
        ;;
esac

audit_expected=$(awk -F '\t' '$1 == "audit_events" { print $2 }' "$counts_file")
audit_actual=$(psql -X -A -t --set=ON_ERROR_STOP=1 $connection \
    --dbname="$restore_db" --command="SELECT count(*) FROM public.audit_events")
[ "$audit_actual" = "$audit_expected" ] || {
    echo "Audit row count changed during TRUNCATE guard check" >&2
    exit 1
}

echo "T-021 subset: published flow rows=$critical_flow, relationship orphans=0"
echo "Audit TRUNCATE guard: enforced; audit_events rows=$audit_actual"
echo "Restore smoke passed"
