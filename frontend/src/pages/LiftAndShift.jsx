import React, { useEffect, useMemo, useState } from 'react';
import { Box, Typography, Paper, Chip, Button, Grid, Alert, CircularProgress, Stack } from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import LockIcon from '@mui/icons-material/Lock';

// Two-plane / 28-stage / 9-phase visualisation for the lift-and-shift pipeline.
// Mirrors run_local_lift_and_shift.STAGES and lift_and_shift_pipeline.asl.json.

const PHASE_COLORS = {
  ASSESS: '#90caf9', PROVISION: '#ce93d8', CODE: '#a5d6a7',
  CONFIG: '#fff59d', DATA_PREP: '#ffcc80', DATA_LOAD: '#ef9a9a',
  VALIDATE: '#80cbc4', CUTOVER: '#f48fb1', RUN: '#bcaaa4',
};

const LANE_FOR = (handler, extra = {}) => {
  if (!handler) return 'GATE';
  if (handler.includes('migration-cockpit')) return 'MC';
  if (handler.includes('ltmom'))             return 'LTMOM';
  if (handler.includes('idoc'))              return 'IDOC';
  if (handler.includes('transport'))         return 'CTS+';
  if (handler.includes('bc-set'))            return 'BC SET';
  if (handler.includes('cutover') || handler.includes('rollback')) return 'CUTOVER';
  return 'ORCH';
};

function StageCell({ stage }) {
  const phaseColor = PHASE_COLORS[stage.phase] || '#e0e0e0';
  const isGate = !stage.handler;
  return (
    <Paper elevation={2} sx={{
      p: 1.2, m: 0.5, minWidth: 180, borderLeft: `6px solid ${phaseColor}`,
      bgcolor: isGate ? 'grey.100' : 'background.paper',
    }}>
      <Stack direction="row" alignItems="center" spacing={1}>
        {isGate && <LockIcon fontSize="small" />}
        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>{stage.id}</Typography>
        <Chip size="small" label={LANE_FOR(stage.handler, stage.extra)} variant="outlined" />
      </Stack>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5, wordBreak: 'break-word' }}>
        {stage.handler || `manual gate: ${(stage.extra || {}).gate || '-'}`}
      </Typography>
    </Paper>
  );
}

export default function LiftAndShift() {
  const [stages, setStages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState(null);

  useEffect(() => {
    fetch('/api/pipeline/lift-and-shift/stages', { credentials: 'include' })
      .then(r => r.json())
      .then(d => { setStages(d.stages || []); setLoading(false); })
      .catch(e => { setErr(String(e)); setLoading(false); });
  }, []);

  const phases = useMemo(() => {
    const map = new Map();
    for (const s of stages) {
      if (!map.has(s.phase)) map.set(s.phase, []);
      map.get(s.phase).push(s);
    }
    return Array.from(map.entries());
  }, [stages]);

  const start = async (mode) => {
    setRunning(true); setRunResult(null);
    try {
      const r = await fetch(`/api/pipeline/lift-and-shift${mode}`, {
        method: 'POST', credentials: 'include',
      });
      setRunResult(await r.json());
    } catch (e) { setRunResult({ error: String(e) }); }
    finally { setRunning(false); }
  };

  if (loading) return <Box sx={{ p: 4 }}><CircularProgress /></Box>;

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h4" gutterBottom>Lift-and-Shift Pipeline</Typography>
      <Typography variant="body2" color="text.secondary" gutterBottom>
        Greenfield S/4HANA on AWS. <strong>Two-plane architecture:</strong>
        {' '}orchestration plane reads ECC and stages artifacts to S3;
        execution plane is 100% SAP-shipped tools (Migration Cockpit / LTMOM /
        IDoc inbound / CTS+ / BC Sets). Zero direct BAPI writes into the target.
      </Typography>

      <Stack direction="row" spacing={1} sx={{ my: 2 }}>
        <Button variant="contained" startIcon={<PlayArrowIcon />} disabled={running}
                onClick={() => start('')}>Run full pipeline</Button>
        <Button variant="outlined" disabled={running} onClick={() => start('/assess')}>Assess only</Button>
        <Button variant="outlined" disabled={running} onClick={() => start('/code')}>Through code</Button>
        <Button variant="outlined" disabled={running} onClick={() => start('/data')}>Through data load</Button>
      </Stack>

      {err && <Alert severity="error" sx={{ my: 2 }}>{err}</Alert>}
      {runResult && (
        <Alert severity={runResult.error ? 'error' : 'success'} sx={{ my: 2 }}>
          {runResult.error || `Run started${runResult.run_id ? ': ' + runResult.run_id : ''}`}
        </Alert>
      )}

      <Grid container spacing={2}>
        {phases.map(([phase, stageList]) => (
          <Grid item xs={12} key={phase}>
            <Paper sx={{ p: 2, bgcolor: PHASE_COLORS[phase] + '22' }}>
              <Typography variant="h6" gutterBottom>{phase}</Typography>
              <Stack direction="row" sx={{ flexWrap: 'wrap' }}>
                {stageList.map(s => <StageCell key={s.id} stage={s} />)}
              </Stack>
            </Paper>
          </Grid>
        ))}
      </Grid>
    </Box>
  );
}
