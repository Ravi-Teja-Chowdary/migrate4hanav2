# target-system module

Greenfield S/4HANA target landscape for the **lift-and-shift** model.

## What this module provisions

| Resource | Purpose |
|---|---|
| IAM role + instance profile | Lets SAP hosts pull from S3 staging and accept SSM Run Command (the channel `transport-import-executor` uses to run `tp`) |
| Security groups (`hana`, `app`) | HANA SQL ports + RFC gateway + ICM HTTPS (44300+ for `idoc_xml` SICF and OData) |
| EFS file system | Shared `/usr/sap/trans` between BUILD and target — `transport-file-placer` lands cofiles/datafiles here |
| SSM parameters | `target-provisioner` reads `build_sid`, `target_sid`, `trans_efs`, and `sap_instance_profile` from `/migrate4hana/<prefix>/` |

## What this module deliberately does NOT do

* It does not run **SWPM**. SWPM is invoked by `lambda/target-provisioner`
  in `sandbox` mode (SSM Run Command), or by **Launch Wizard for SAP** in
  `launch_wizard` mode. Both paths are SAP-supported.
* It does not configure **HSR** or cluster — those are Launch Wizard
  concerns or customer-Basis concerns.
* It does not create the BUILD system. We assume the customer's existing
  ECC landscape provides an ABAP development system (or a fresh sandbox)
  whose RFC connection string is supplied to `transport-artifact-builder`
  via Secrets Manager.

## Sample usage

```hcl
module "target_system" {
  source = "../../modules/target-system"

  name_prefix         = "m4h-prod"
  vpc_id              = module.vpc.vpc_id
  private_subnets     = module.vpc.private_subnets
  build_sid           = "BLD"
  target_sid          = "S4H"
  staging_bucket_arn  = module.s3_staging.bucket_arn
  tags                = var.tags
}
```
