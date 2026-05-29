import {
  GitBranch, Layers, Scissors, Database, Code2, FlaskConical, FileText,
} from 'lucide-react';
import { COMMAND_GROUPS } from '../lib/commands';
import { Card, PageHeader, SectionTitle, CommandBlock, ACCENT } from '../components/ui';

const ICONS = { GitBranch, Layers, Scissors, Database, Code2, FlaskConical, FileText };

export default function CommandCenter() {
  return (
    <div className="space-y-7">
      <PageHeader
        title="Command" accentWord="Center"
        subtitle="Every action this platform can perform from the terminal — copy and run, or trigger the live ones from their page."
      />

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        {COMMAND_GROUPS.map((g) => {
          const Icon = ICONS[g.icon] || GitBranch;
          const a = ACCENT[g.accent] || ACCENT.indigo;
          return (
            <Card key={g.id} className="p-6">
              <SectionTitle icon={Icon} title={g.title} subtitle={`${g.commands.length} command${g.commands.length > 1 ? 's' : ''}`} />
              <div className="space-y-4">
                {g.commands.map((c) => (
                  <div key={c.id}>
                    <div className="flex items-center gap-2 mb-1.5">
                      <span className={`w-1.5 h-1.5 rounded-full ${a.dot}`} />
                      <span className="text-[13px] font-semibold text-ink-900">{c.label}</span>
                    </div>
                    <p className="text-xs text-ink-400 mb-2 ml-3.5">{c.desc}</p>
                    <CommandBlock cmd={c.cmd} />
                  </div>
                ))}
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
