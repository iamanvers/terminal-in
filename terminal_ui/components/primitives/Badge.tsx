import clsx from 'clsx'

const REGIME_COLORS: Record<string, string> = {
  strong_bull:  'bg-emerald-900 text-emerald-300 border-emerald-700',
  bull:         'bg-green-900 text-green-300 border-green-700',
  sideways:     'bg-yellow-900 text-yellow-300 border-yellow-700',
  bear:         'bg-orange-900 text-orange-300 border-orange-700',
  strong_bear:  'bg-red-900 text-red-300 border-red-700',
  high_vol:     'bg-purple-900 text-purple-300 border-purple-700',
}

const SENTIMENT_COLORS: Record<string, string> = {
  positive: 'text-pos',
  negative: 'text-neg',
  neutral:  'text-muted',
}

const IMPACT_COLORS: Record<string, string> = {
  high:   'text-neg font-semibold',
  medium: 'text-accent',
  low:    'text-muted',
}

type Props = {
  variant: 'regime' | 'sentiment' | 'impact' | 'side'
  value: string
}

export default function Badge({ variant, value }: Props) {
  if (variant === 'regime') {
    return (
      <span className={clsx(
        'px-2 py-0.5 rounded text-[10px] font-semibold border uppercase tracking-wide',
        REGIME_COLORS[value] ?? 'bg-gray-900 text-gray-300 border-gray-700',
      )}>
        {value.replace('_', ' ')}
      </span>
    )
  }
  if (variant === 'sentiment') {
    return <span className={clsx('text-[10px]', SENTIMENT_COLORS[value])}>{value}</span>
  }
  if (variant === 'impact') {
    return <span className={clsx('text-[10px]', IMPACT_COLORS[value])}>{value}</span>
  }
  if (variant === 'side') {
    return (
      <span className={clsx('text-[10px] font-bold', value === 'BUY' ? 'text-pos' : 'text-neg')}>
        {value}
      </span>
    )
  }
  return <span>{value}</span>
}
