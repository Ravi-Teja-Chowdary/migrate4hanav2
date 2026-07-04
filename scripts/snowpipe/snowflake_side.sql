-- Snowpipe auto-ingest, Snowflake side (customer's DBA runs this once).
-- Companion to terraform/modules/snowpipe.
--
-- Prereq (from terraform outputs, run inside your Terraform workspace):
--   terraform output -raw snowpipe_sns_topic_arn
--   terraform output -raw snowpipe_stage_integration_role_arn
-- Copy those two values into the placeholders below.
--
-- Order of operations
--   1. CREATE STORAGE INTEGRATION      (creates the S3 read integration)
--   2. DESC STORAGE INTEGRATION        (retrieves AWS account + external ID)
--   3. Feed those two values back into `terraform.tfvars`:
--         snowflake_aws_account_id = "..."      (from STORAGE_AWS_IAM_USER_ARN)
--         snowflake_external_id    = "..."      (from STORAGE_AWS_EXTERNAL_ID)
--      Re-run `terraform apply` -- the IAM role trust policy tightens.
--   4. CREATE STAGE                    (external S3 stage using the integration)
--   5. CREATE TABLE                    (raw landing zone; row per JSONL line)
--   6. CREATE PIPE                     (auto-ingest via SNS notification)
-- ============================================================================

-- 1. Storage integration
CREATE OR REPLACE STORAGE INTEGRATION m4h_stage_int
  TYPE = EXTERNAL_STAGE
  STORAGE_PROVIDER = 'S3'
  ENABLED = TRUE
  STORAGE_AWS_ROLE_ARN = '<PASTE: snowpipe_stage_integration_role_arn>'
  STORAGE_ALLOWED_LOCATIONS = ('s3://<stage_bucket_name>/snowflake-stage/');

-- 2. Retrieve AWS user + external id (populate terraform vars, apply, then move on)
DESC STORAGE INTEGRATION m4h_stage_int;

-- 4. External stage on S3
CREATE OR REPLACE STAGE m4h_stage
  URL = 's3://<stage_bucket_name>/snowflake-stage/'
  STORAGE_INTEGRATION = m4h_stage_int
  FILE_FORMAT = (TYPE = JSON STRIP_OUTER_ARRAY = FALSE);

-- 5. Raw table (VARIANT keeps the JSON blob; downstream views do the flattening)
CREATE OR REPLACE TABLE m4h_raw (
  tenant_id     STRING,
  object_type   STRING,
  source_key    STRING,
  loaded_at     TIMESTAMP_LTZ,
  row_data      VARIANT,
  file_name     STRING,
  loaded_from_file_ts TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- 6. Pipe. AUTO_INGEST=TRUE watches the SNS topic.
CREATE OR REPLACE PIPE m4h_pipe
  AUTO_INGEST = TRUE
  AWS_SNS_TOPIC = '<PASTE: snowpipe_sns_topic_arn>'
  AS
  COPY INTO m4h_raw (
    tenant_id, object_type, source_key, loaded_at, row_data, file_name
  )
  FROM (
    SELECT
      SPLIT_PART(METADATA$FILENAME, '/', 2)     AS tenant_id,
      SPLIT_PART(METADATA$FILENAME, '/', 3)     AS object_type,
      $1:source_key::STRING                     AS source_key,
      $1:_loaded_at::TIMESTAMP_LTZ              AS loaded_at,
      $1:row                                    AS row_data,
      METADATA$FILENAME                         AS file_name
    FROM @m4h_stage
  )
  FILE_FORMAT = (TYPE = JSON);

-- Verification queries (safe to run any time)
-- Count of rows loaded in the last 24h per tenant/object
SELECT tenant_id, object_type, COUNT(*) AS rows_loaded,
       MIN(loaded_at) AS first_seen,
       MAX(loaded_at) AS last_seen
FROM   m4h_raw
WHERE  loaded_at > DATEADD('hour', -24, CURRENT_TIMESTAMP())
GROUP BY 1, 2
ORDER BY 1, 2;

-- Pipe status
SELECT SYSTEM$PIPE_STATUS('m4h_pipe');

-- Load history (last 60 min) for a specific object -- verifier Lambda uses this
SELECT tenant_id, object_type, SUM(row_data:_ok::INT) AS ok_rows,
       COUNT(*) AS total_rows
FROM   m4h_raw
WHERE  loaded_at > DATEADD('minute', -60, CURRENT_TIMESTAMP())
GROUP BY 1, 2;
