import { useMemo, useState } from 'react';
import {
  GitBranch, Layers, Scissors, Database, Code2, FlaskConical, FileText,
  Server, KeyRound, Building2, CloudCog, Network, Activity, Terminal,
} from 'lucide-react';
import { COMMAND_GROUPS } from '../lib/commands';
import { Panel, PageHeader, MetricTile, SearchBox, CmdLine, EmptyState, StatusPill } from '../components/dd';

// Icon map for group keys; falls back to Terminal.
const ICONS = {
  GitBranch, Layers, Scissors, Database, Code2, FlaskConical, FileText,
  Server, KeyRound, Building2, CloudCog, Network, Activity, Terminal,
};

export default function CommandCenter() {
  const [q, setQ] = useState('');
  const [activeGroup, setActiveGroup] = useState('all');

  const filtered = useMemo(() => {
    const term = q.toLowerCase().trim();
    return COMMAND_GROUPS
      .map((g) => ({
        ...g,
        commands: g.commands.filter((c) => {
          if (activeGroup !== 'all' && g.id !== activeGroup) return false;
          if (!term) return true;
          return (
            c.label.toLowerCase().includes(term) ||
            c.cmd.toLowerCase().includes(term) ||
            c.desc.toLowerCase().includes(term) ||
            g.title.toLowerCase().includes(term)
          );
        }),
      }))
      .filter((g) => g.commands.length > 0);
  }, [q, activeGroup]);

  const totalCmds = COMMAND_GROUPS.reduce((a, g) => a + g.commands.length, 0);
  const visibleCmds = filtered.reduce((a, g) => a + g.commands.length, 0);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Command Center"
        breadcrumb={['Migrate4HANA', 'Commands']}
        subtitle={`${totalCmds} terminal-equivalent actions across ${COMMAND_GROUPS.length} categories. Click any to copy.`}
        actions={<SearchBox value={q} onChange={setQ} placeholder="Search commands…" />}
      />

      {/* Stat strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <MetricTile label="Total commands" value={totalCmds} sub={`${COMMAND_GROUPS.length} categories`} />
        <MetricTile label="Visible" value={visibleCmds} sub={q ? `filter "${q}"` : 'no filter'} />
        <MetricTile label="PowerShell" value={COMMAND_GROUPS.reduce((a, g) => a + g.commands.filter((c) => c.cmd.startsWith('powershell')).length, 0)} sub="Windows scripts" />
        <MetricTile label="Python entry points" value={COMMAND_GROUPS.reduce((a, g) => a + g.commands.filter((c) => c.cmd.startsWith('python')).length, 0)} sub="cross-platform" />
      </div>

      {/* Category chips — clickable filters */}
      <Panel title="Categories" icon={Terminal} flush>
        <div className="flex flex-wrap gap-1.5 p-3">
          <button
            onClick={() => setActiveGroup('all')}
            className={`btn btn-sm ${activeGroup === 'all' ? 'btn-primary' : ''}`}
          >
            All <span className="text-[10px] opacity-70 ml-1">{totalCmds}</span>
          </button>
          {COMMAND_GROUPS.map((g) => {
            const Icon = ICONS[g.icon] || Terminal;
            return (
              <button
                key={g.id}
                onClick={() => setActiveGroup(activeGroup === g.id ? 'all' : g.id)}
                className={`btn btn-sm ${activeGroup === g.id ? 'btn-primary' : ''}`}
                title={g.title}
              >
                <Icon size={12} /> {g.title} <span className="text-[10px] opacity-70 ml-1">{g.commands.length}</span>
              </button>
            );
          })}
        </div>
      </Panel>

      {/* Groups */}
      {filtered.length === 0 ? (
        <Panel>
          <EmptyState
            icon={Terminal}
            title="No commands match"
            hint="Adjust the search or pick a different category."
          />
        </Panel>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
          {filtered.map((g) => {
            const Icon = ICONS[g.icon] || Terminal;
            return (
              <Panel
                key={g.id}
                title={g.title}
                icon={Icon}
                actions={<StatusPill tone="muted" dot={false}>{g.commands.length}</StatusPill>}
              >
                <div className="space-y-3.5">
                  {g.commands.map((c) => (
                    <div key={c.id}>
                      <div className="flex items-start justify-between gap-3 mb-1.5">
                        <div className="min-w-0">
                          <div className="text-[12.5px] font-semibold text-ink-1">{c.label}</div>
                          <p className="text-[11.5px] text-ink-3 leading-relaxed mt-0.5">{c.desc}</p>
                        </div>
                        <span className="kbd shrink-0">
                          {c.cmd.startsWith('powershell') ? 'ps1'
                           : c.cmd.startsWith('python') ? 'py'
                           : c.cmd.startsWith('cd') ? 'sh'
                           : 'cmd'}
                        </span>
                      </div>
                      <CmdLine cmd={c.cmd} />
                    </div>
                  ))}
                </div>
              </Panel>
            );
          })}
        </div>
      )}

      <Panel title="Tips" icon={Terminal}>
        <div className="text-[12px] text-ink-2 space-y-2 leading-relaxed">
          <div>• Hover the <span className="kbd">ps1</span> / <span className="kbd">py</span> chip on each command to see its runtime.</div>
          <div>• <span className="kbd">⌘K</span> from anywhere opens the global jump palette.</div>
          <div>• Long-running ops (battletest, package-lambdas, terraform apply) are best driven from a terminal; this page is a copy-paste catalog of every supported command.</div>
        </div>
      </Panel>
    </div>
  );
}
