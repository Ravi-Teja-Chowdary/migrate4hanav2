# Bedrock VPC PrivateLink endpoints removed - this stack uses the direct
# Anthropic API (api.anthropic.com via NAT egress, key in Secrets Manager).
#
# To re-enable Bedrock later, restore the two interface endpoints:
#   - com.amazonaws.<region>.bedrock-runtime
#   - com.amazonaws.<region>.bedrock-agent-runtime
# (~$7.30/mo each + data charges). The module's vpc_id /
# private_subnet_ids / vpce_security_group_id variables are kept so callers
# don't need to change when endpoints come back.
