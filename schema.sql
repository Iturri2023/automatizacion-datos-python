-- Instalación explícita de la Iteración 4. No borra ni migra datos existentes.
-- TIMESTAMPTZ almacena instantes; PGTZ determina su presentación en la sesión.
CREATE TABLE IF NOT EXISTS public.processing_runs (
    id BIGSERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ,
    mode TEXT NOT NULL CHECK (mode IN ('default', 'single', 'batch')),
    status TEXT NOT NULL DEFAULT 'RUNNING'
        CHECK (status IN ('RUNNING', 'COMPLETED', 'PARTIAL', 'FAILED')),
    files_found INTEGER NOT NULL DEFAULT 0 CHECK (files_found >= 0),
    files_completed INTEGER NOT NULL DEFAULT 0 CHECK (files_completed >= 0),
    files_failed INTEGER NOT NULL DEFAULT 0 CHECK (files_failed >= 0),
    original_count BIGINT NOT NULL DEFAULT 0 CHECK (original_count >= 0),
    duplicate_count BIGINT NOT NULL DEFAULT 0 CHECK (duplicate_count >= 0),
    processed_count BIGINT NOT NULL DEFAULT 0 CHECK (processed_count >= 0),
    missing_count BIGINT NOT NULL DEFAULT 0 CHECK (missing_count >= 0),
    valid_count BIGINT NOT NULL DEFAULT 0 CHECK (valid_count >= 0),
    rejected_count BIGINT NOT NULL DEFAULT 0 CHECK (rejected_count >= 0),
    CHECK (finished_at IS NULL OR finished_at >= started_at),
    CHECK ((status = 'RUNNING') = (finished_at IS NULL)),
    CHECK (files_completed + files_failed <= files_found),
    CHECK (original_count = duplicate_count + processed_count),
    CHECK (processed_count = valid_count + rejected_count),
    CHECK (missing_count <= processed_count)
);

CREATE TABLE IF NOT EXISTS public.processed_files (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES public.processing_runs(id) ON DELETE CASCADE,
    source_name TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_format TEXT NOT NULL CHECK (source_format IN ('csv', 'xlsx')),
    -- Nulo solo cuando no fue posible leer los bytes (ej. archivo inexistente).
    source_sha256 TEXT CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    sheet_name TEXT,
    status TEXT NOT NULL CHECK (status IN ('COMPLETED', 'FAILED')),
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ NOT NULL CHECK (finished_at >= started_at),
    original_count BIGINT CHECK (original_count >= 0),
    duplicate_count BIGINT CHECK (duplicate_count >= 0),
    processed_count BIGINT CHECK (processed_count >= 0),
    missing_count BIGINT CHECK (missing_count >= 0),
    valid_count BIGINT CHECK (valid_count >= 0),
    rejected_count BIGINT CHECK (rejected_count >= 0),
    valid_output_path TEXT,
    rejected_output_path TEXT,
    error_message TEXT,
    CHECK ((status = 'COMPLETED' AND original_count IS NOT NULL
        AND duplicate_count IS NOT NULL AND processed_count IS NOT NULL
        AND missing_count IS NOT NULL AND valid_count IS NOT NULL
        AND rejected_count IS NOT NULL AND source_sha256 IS NOT NULL
        AND error_message IS NULL AND valid_output_path IS NOT NULL
        AND rejected_output_path IS NOT NULL)
        OR (status = 'FAILED' AND original_count IS NULL AND duplicate_count IS NULL
        AND processed_count IS NULL AND missing_count IS NULL AND valid_count IS NULL
        AND rejected_count IS NULL AND error_message IS NOT NULL)),
    CHECK (original_count = duplicate_count + processed_count),
    CHECK (processed_count = valid_count + rejected_count),
    CHECK (missing_count <= processed_count)
);

CREATE TABLE IF NOT EXISTS public.processed_records (
    id BIGSERIAL PRIMARY KEY,
    processed_file_id BIGINT NOT NULL REFERENCES public.processed_files(id) ON DELETE CASCADE,
    row_type TEXT NOT NULL CHECK (row_type IN ('VALID', 'REJECTED')),
    -- Numeración desde 1, sin encabezado, independiente para cada salida.
    row_number BIGINT NOT NULL CHECK (row_number > 0),
    data JSONB NOT NULL CHECK (jsonb_typeof(data) = 'object'),
    validation_errors JSONB NOT NULL CHECK (jsonb_typeof(validation_errors) = 'array'),
    CHECK ((row_type = 'VALID' AND validation_errors = '[]'::jsonb)
        OR (row_type = 'REJECTED' AND jsonb_array_length(validation_errors) > 0))
);

-- Solo los cuatro índices de consulta requeridos, además de las claves primarias.
CREATE INDEX IF NOT EXISTS processing_runs_date_idx ON public.processing_runs(started_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS processed_files_run_idx ON public.processed_files(run_id);
CREATE INDEX IF NOT EXISTS processed_files_sha_idx ON public.processed_files(source_sha256);
CREATE INDEX IF NOT EXISTS processed_records_file_type_idx ON public.processed_records(processed_file_id, row_type);

-- La aplicación guarda archivo + registros en una sola transacción. Estas
-- comprobaciones impiden asociar registros a archivos FAILED también vía SQL.
CREATE OR REPLACE FUNCTION public.check_completed_file() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_TABLE_NAME = 'processed_records' THEN
        PERFORM 1 FROM public.processed_files
            WHERE id = NEW.processed_file_id AND status = 'COMPLETED' FOR SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Los registros requieren un archivo COMPLETED' USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.status = 'FAILED' AND EXISTS (
        SELECT 1 FROM public.processed_records WHERE processed_file_id = NEW.id
    ) THEN
        RAISE EXCEPTION 'Un archivo FAILED no puede tener registros' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'records_completed_file'
                   AND tgrelid = 'public.processed_records'::regclass) THEN
        CREATE TRIGGER records_completed_file BEFORE INSERT OR UPDATE ON public.processed_records
            FOR EACH ROW EXECUTE FUNCTION public.check_completed_file();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'files_no_partial_records'
                   AND tgrelid = 'public.processed_files'::regclass) THEN
        CREATE TRIGGER files_no_partial_records BEFORE UPDATE ON public.processed_files
            FOR EACH ROW EXECUTE FUNCTION public.check_completed_file();
    END IF;
END $$;
