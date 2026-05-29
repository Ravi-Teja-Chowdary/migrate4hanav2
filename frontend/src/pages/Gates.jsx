import React, { useEffect, useState, useCallback } from 'react';
import {
  Box, Typography, Paper, Chip, Button, Stack, Alert, CircularProgress,
  Dialog, DialogTitle, DialogContent, DialogActions, TextField,
} from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import CancelIcon from '@mui/icons-material/Cancel';
import RefreshIcon from '@mui/icons-material/Refresh';

// Manual approval gates page for the lift-and-shift pipeline.
// Polls /api/gates and lets approvers send_task_success / send_task_failure to
// Step Functions via api_server endpoints.

const POLL_INTERVAL_MS = 10000;

export default function Gates() {
  const [gates, setGates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [actioning, setActioning] = useState(null);
  const [rejectFor, setRejectFor] = useState(null);
  const [rejectReason, setRejectReason] = useState('');
  const [approver, setApprover] = useState(localStorage.getItem('m4h_approver') || '');

  const load = useCallback(async () => {
    try {
      const r = await fetch('/api/gates');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = await r.json();
      setGates(j.gates || []);
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, POLL_INTERVAL_MS);
    return () => clearInterval(t);
  }, [load]);

  useEffect(() => {
    localStorage.setItem('m4h_approver', approver);
  }, [approver]);

  const approve = async (gate) => {
    setActioning(gate.gate_id);
    try {
      const r = await fetch(`/api/gates/${encodeURIComponent(gate.gate_id)}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approver: approver || 'unknown' }),
      });
      if (!r.ok) throw new Error(`approve failed: HTTP ${r.status}`);
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setActioning(null);
    }
  };

  const reject = async () => {
    if (!rejectFor) return;
    setActioning(rejectFor.gate_id);
    try {
      const r = await fetch(`/api/gates/${encodeURIComponent(rejectFor.gate_id)}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approver: approver || 'unknown', reason: rejectReason }),
      });
      if (!r.ok) throw new Error(`reject failed: HTTP ${r.status}`);
      setRejectFor(null);
      setRejectReason('');
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setActioning(null);
    }
  };

  const pending = gates.filter((g) => g.status === 'pending' || !g.status);
  const decided = gates.filter((g) => g.status && g.status !== 'pending');

  return (
    <Box sx={{ p: 4, maxWidth: 1200, mx: 'auto' }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 3 }}>
        <Box>
          <Typography variant="h4" sx={{ fontWeight: 700, color: '#0f172a' }}>
            Manual Approval Gates
          </Typography>
          <Typography variant="body2" sx={{ color: '#9ca3af', mt: 0.5 }}>
            Lift-and-shift pipeline pauses here for human GO/NO-GO decisions.
          </Typography>
        </Box>
        <Button startIcon={<RefreshIcon />} onClick={load} variant="outlined">
          Refresh
        </Button>
      </Stack>

      <TextField
        label="Approver (your name / email)"
        value={approver}
        onChange={(e) => setApprover(e.target.value)}
        size="small"
        sx={{ mb: 3, width: 360 }}
        helperText="Saved locally; recorded with each decision."
      />

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {loading && <CircularProgress />}

      <Typography variant="h6" sx={{ mt: 2, mb: 1, color: '#0f172a' }}>
        Pending ({pending.length})
      </Typography>
      {pending.length === 0 && !loading && (
        <Alert severity="info">No pending gates.</Alert>
      )}
      <Stack spacing={2}>
        {pending.map((g) => (
          <Paper key={g.gate_id} sx={{ p: 2.5, bgcolor: 'rgba(15, 23, 42,0.04)' }}>
            <Stack direction="row" alignItems="flex-start" spacing={2}>
              <Box sx={{ flex: 1 }}>
                <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                  <Chip label={g.gate || 'GATE'} color="warning" size="small" />
                  <Chip label={g.run_id || '—'} size="small" variant="outlined" />
                  <Typography variant="caption" sx={{ color: '#9ca3af' }}>
                    {g.created_at}
                  </Typography>
                </Stack>
                <Typography variant="body2" sx={{ color: '#d1d5db', whiteSpace: 'pre-wrap' }}>
                  {typeof g.input === 'string' ? g.input : JSON.stringify(g.input, null, 2)}
                </Typography>
              </Box>
              <Stack spacing={1}>
                <Button
                  variant="contained"
                  color="success"
                  startIcon={<CheckCircleIcon />}
                  disabled={actioning === g.gate_id || !approver}
                  onClick={() => approve(g)}
                >
                  Approve
                </Button>
                <Button
                  variant="outlined"
                  color="error"
                  startIcon={<CancelIcon />}
                  disabled={actioning === g.gate_id || !approver}
                  onClick={() => setRejectFor(g)}
                >
                  Reject
                </Button>
              </Stack>
            </Stack>
          </Paper>
        ))}
      </Stack>

      {decided.length > 0 && (
        <>
          <Typography variant="h6" sx={{ mt: 4, mb: 1, color: '#0f172a' }}>
            Recent Decisions
          </Typography>
          <Stack spacing={1}>
            {decided.slice(0, 20).map((g) => (
              <Paper key={g.gate_id} sx={{ p: 1.5, bgcolor: 'rgba(15, 23, 42,0.02)' }}>
                <Stack direction="row" spacing={2} alignItems="center">
                  <Chip
                    label={g.status}
                    color={g.status === 'approved' ? 'success' : 'error'}
                    size="small"
                  />
                  <Typography variant="body2" sx={{ color: '#d1d5db' }}>
                    {g.gate} · {g.run_id}
                  </Typography>
                  <Typography variant="caption" sx={{ color: '#9ca3af', ml: 'auto' }}>
                    {g.decided_by} @ {g.decided_at}
                  </Typography>
                </Stack>
              </Paper>
            ))}
          </Stack>
        </>
      )}

      <Dialog open={!!rejectFor} onClose={() => setRejectFor(null)} fullWidth maxWidth="sm">
        <DialogTitle>Reject gate: {rejectFor?.gate}</DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ mb: 2 }}>
            Rejection fails the Step Functions execution. Provide a reason for the audit log.
          </Typography>
          <TextField
            autoFocus
            fullWidth
            multiline
            minRows={3}
            label="Reason"
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRejectFor(null)}>Cancel</Button>
          <Button
            variant="contained"
            color="error"
            disabled={!rejectReason.trim() || actioning}
            onClick={reject}
          >
            Confirm Reject
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
