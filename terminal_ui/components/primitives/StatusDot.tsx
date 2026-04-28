import clsx from 'clsx'

type Props = { connected: boolean }

export default function StatusDot({ connected }: Props) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={clsx(
        'inline-block w-1.5 h-1.5 rounded-full',
        connected ? 'bg-pos animate-pulse' : 'bg-neg',
      )} />
      <span className="text-muted text-[9px]">{connected ? 'LIVE' : 'DISCONNECTED'}</span>
    </span>
  )
}
