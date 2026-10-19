use palaco_citadel::ExecutionBoundary;
use palaco_eventbus::EventEnvelope;
use palaco_evolution::EvolutionProposal;
use palaco_foundation::{
    AuthorityState, ContractDisposition, ContractError, EvidenceRef, FailClosed, Validatable,
};
use palaco_kernel::KernelCycle;
use palaco_quay::ProvenanceRecord;
use palaco_runtime::RuntimePlan;
use palaco_runtime::inspection::{inspect_plan, write_plan_inspection_json};

fn cycle(authority: AuthorityState) -> Result<KernelCycle, ContractError> {
    let evidence = EvidenceRef::new("PVS-002-EVIDENCE-001")?;
    let event = EventEnvelope::new("execution.requested", evidence);
    let record = ProvenanceRecord::new(event, authority);
    let boundary = ExecutionBoundary::new(record);
    let plan = RuntimePlan::new(boundary);
    Ok(KernelCycle::new(plan))
}

#[test]
fn authorized_evidence_path_reaches_execute_without_widening_authority() -> Result<(), ContractError>
{
    let cycle = cycle(AuthorityState::Authorized)?;

    assert_eq!(cycle.disposition(), ContractDisposition::Execute);
    assert!(cycle.can_execute());
    cycle.validate()?;

    Ok(())
}

#[test]
fn revoked_authority_remains_denied_across_all_downstream_boundaries() -> Result<(), ContractError>
{
    let cycle = cycle(AuthorityState::Revoked)?;

    assert_eq!(cycle.disposition(), ContractDisposition::Deny);
    assert!(!cycle.can_execute());
    assert_eq!(cycle.fail_closed(), ContractDisposition::Deny);

    Ok(())
}

#[test]
fn indoubt_authority_is_held_and_never_executes() -> Result<(), ContractError> {
    let cycle = cycle(AuthorityState::InDoubt)?;

    assert_eq!(cycle.disposition(), ContractDisposition::Hold);
    assert!(!cycle.can_execute());

    Ok(())
}

#[test]
fn empty_evidence_reference_is_rejected_before_event_transport() {
    assert_eq!(EvidenceRef::new(""), Err(ContractError::MissingEvidence));
}

#[test]
fn evolution_proposal_cannot_self_authorize_execution() -> Result<(), ContractError> {
    let evidence = EvidenceRef::new("PVS-002-EVOLUTION-001")?;
    let proposal = EvolutionProposal::new(evidence);

    proposal.validate()?;
    assert_eq!(proposal.requested_disposition(), ContractDisposition::Hold);

    Ok(())
}

#[test]
fn plan_inspection_preserves_all_authority_dispositions_without_execution()
-> Result<(), ContractError> {
    for (authority, disposition) in [
        (AuthorityState::Authorized, ContractDisposition::Execute),
        (AuthorityState::Revoked, ContractDisposition::Deny),
        (AuthorityState::Expired, ContractDisposition::Deny),
        (AuthorityState::InDoubt, ContractDisposition::Hold),
    ] {
        let evidence = EvidenceRef::new("SYNTHETIC-PLAN-INSPECTION")?;
        let event = EventEnvelope::new("inspection.only", evidence);
        let record = ProvenanceRecord::new(event, authority);
        let plan = RuntimePlan::new(ExecutionBoundary::new(record));
        let original = plan.clone();
        let report = inspect_plan(&plan);

        assert_eq!(report.disposition, disposition);
        assert_eq!(report.validation, plan.validate());
        assert_eq!(report.validation, Ok(()));
        assert_eq!(plan, original);
        assert_eq!(inspect_plan(&plan), report);

        let mut local_report = report;
        local_report.disposition = ContractDisposition::Execute;
        local_report.validation = Err(ContractError::MissingEvidence);
        assert_ne!(local_report, inspect_plan(&plan));
        assert_eq!(plan, original);
    }
    Ok(())
}

#[test]
fn plan_json_reports_are_exact_and_exclude_caller_supplied_strings()
-> Result<(), Box<dyn std::error::Error>> {
    for (authority, disposition) in [
        (AuthorityState::Authorized, "execute"),
        (AuthorityState::Revoked, "deny"),
        (AuthorityState::Expired, "deny"),
        (AuthorityState::InDoubt, "hold"),
    ] {
        let evidence = EvidenceRef::new("PRIVATE-\"EVIDENCE\nIDENTIFIER")?;
        let event = EventEnvelope::new("PRIVATE-TOPIC", evidence);
        let plan = RuntimePlan::new(ExecutionBoundary::new(ProvenanceRecord::new(
            event, authority,
        )));
        let original = plan.clone();
        let mut bytes = Vec::new();
        write_plan_inspection_json(&plan, &mut bytes as &mut dyn std::io::Write)?;
        assert_eq!(
            String::from_utf8(bytes)?,
            format!(
                "{{\"schema_version\":1,\"report_type\":\"plan-inspection\",\"disposition\":\"{disposition}\",\"contract_valid\":true,\"execution_performed\":false,\"authority_verified\":false}}\n"
            )
        );
        assert_eq!(plan, original);
    }

    Ok(())
}

#[test]
fn plan_json_handles_short_writes_without_flushing_and_propagates_errors()
-> Result<(), Box<dyn std::error::Error>> {
    use std::io::{self, Write};

    struct ShortWriter(Vec<u8>);
    impl Write for ShortWriter {
        fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
            let count = bytes.len().min(2);
            self.0.extend_from_slice(&bytes[..count]);
            Ok(count)
        }
        fn flush(&mut self) -> io::Result<()> {
            panic!("plan inspection must not flush");
        }
    }
    let event = EventEnvelope::new("inspection", EvidenceRef::new("SYNTHETIC")?);
    let plan = RuntimePlan::new(ExecutionBoundary::new(ProvenanceRecord::new(
        event,
        AuthorityState::Revoked,
    )));
    let mut expected = Vec::new();
    write_plan_inspection_json(&plan, &mut expected)?;
    let mut short = ShortWriter(Vec::new());
    write_plan_inspection_json(&plan, &mut short)?;
    assert_eq!(short.0, expected);

    for capacity in [0, 10] {
        let mut storage = vec![0; capacity];
        let mut destination = &mut storage[..];
        let error = write_plan_inspection_json(&plan, &mut destination)
            .expect_err("undersized destination must fail");
        assert_eq!(error.kind(), io::ErrorKind::WriteZero);
        assert!(destination.is_empty());
        assert_eq!(storage, expected[..capacity]);
    }
    Ok(())
}
