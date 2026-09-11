import {
  cn,
  COMPOSER_AREAS,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  host,
  usePluginI18n,
  useQuery,
  useQueryClient
} from '@hermes/plugin-sdk'
import { useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'codex-quota-status'
const MARKER = 'HERMES_CODEX_QUOTA_JSON '
const REFRESH_MS = 60_000
const MENU_STYLE = {
  width: 'min(30rem, calc(100vw - 1rem))',
  maxWidth: 'calc(100vw - 1rem)',
  maxHeight: 'min(32rem, calc(100vh - 1rem))',
  overflowX: 'hidden',
  overflowY: 'auto'
}

const BUNDLES = {
  en: {
    name: 'Codex Account & Quota',
    selectHeader: 'Select default GPT account for new chats',
    loading: 'GPT default · Loading...',
    unavailable: 'GPT default · Status not synced',
    na: 'No quota data',
    statusDead: 'Unavailable',
    statusCooldown: 'Cooldown {m}m',
    statusReauth: 'Re-authorize to sync plan',
    successSwitch: 'Default account set to {email}; takes effect on new chats',
    failSwitch: 'Codex account operation failed.',
    sessionLabel: '5h',
    weeklyLabel: 'Week',
    monthlyLabel: 'Month'
  },
  zh: {
    name: 'Codex 账号与额度',
    selectHeader: '选择新对话默认 GPT 账号',
    loading: 'GPT默认账号 · 查询中…',
    unavailable: 'GPT默认账号 · 状态未同步',
    na: '暂无额度信息',
    statusDead: '不可用',
    statusCooldown: '冷却 {m} 分钟',
    statusReauth: '需重新授权以同步套餐',
    successSwitch: '默认账号已设为 {email}；新对话生效',
    failSwitch: 'Codex账号操作失败。',
    sessionLabel: '5h',
    weeklyLabel: '周',
    monthlyLabel: '月'
  }
}

function fallbackT(key, params = {}) {
  const isZh = typeof navigator !== 'undefined' && /^zh\b/i.test(navigator.language || '')
  const bundle = isZh ? BUNDLES.zh : BUNDLES.en
  let msg = bundle[key] || BUNDLES.en[key] || key
  if (typeof msg === 'string') {
    for (const [k, v] of Object.entries(params)) {
      msg = msg.replace(new RegExp(`\\{${k}\\}`, 'g'), String(v))
    }
  }
  return msg
}

function parseSnapshot(output) {
  const line = String(output || '')
    .split(/\r?\n/)
    .find(item => item.startsWith(MARKER))
  if (!line) throw new Error('Quota command returned no status payload.')
  return JSON.parse(line.slice(MARKER.length))
}

async function runStatus(extraArgs = []) {
  const result = await host.request('cli.exec', {
    argv: ['codex-quota-status', ...extraArgs, '--json'],
    timeout: 20
  })
  if (result?.blocked || result?.code !== 0) {
    let reason = result?.hint || result?.output || fallbackT('failSwitch')
    try {
      reason = parseSnapshot(result?.output).reason || reason
    } catch {}
    throw new Error(reason)
  }
  return parseSnapshot(result.output)
}

function valueTone(value) {
  if (typeof value !== 'number') return 'text-(--ui-text-tertiary)'
  if (value <= 10) return 'text-(--ui-red)'
  if (value <= 30) return 'text-(--ui-yellow)'
  if (value >= 70) return 'text-(--ui-green)'
  return 'text-foreground'
}

function quotaLine(label, quota, tone, t, key) {
  const value = quota?.remaining
  const rendered = typeof value === 'number' ? `${value}%` : (t ? t('na') : fallbackT('na'))
  return jsxs('span', {
    key,
    className: `inline-flex items-center gap-1 ${tone}`,
    children: [label, jsx('b', { className: valueTone(value), children: rendered })]
  })
}

function quotaSpecsFor(plan, quotas, t) {
  if (plan === 'Free') {
    return [{ key: 'monthly', label: t('monthlyLabel'), quota: quotas?.monthly, tone: 'text-(--ui-purple)' }]
  }
  if (plan === 'Go') {
    const specs = [
      { key: 'session', label: t('sessionLabel'), quota: quotas?.session, tone: 'text-(--ui-cyan)' },
      { key: 'weekly', label: t('weeklyLabel'), quota: quotas?.weekly, tone: 'text-(--ui-purple)' },
      { key: 'monthly', label: t('monthlyLabel'), quota: quotas?.monthly, tone: 'text-(--ui-purple)' }
    ]
    const populated = specs.filter(spec => typeof spec.quota?.remaining === 'number' || Boolean(spec.quota?.reset))
    return populated.length ? populated : specs.slice(0, 2)
  }
  if (plan === 'Pro') {
    return [{ key: 'weekly', label: t('weeklyLabel'), quota: quotas?.weekly, tone: 'text-(--ui-purple)' }]
  }
  return [
    { key: 'session', label: t('sessionLabel'), quota: quotas?.session, tone: 'text-(--ui-cyan)' },
    { key: 'weekly', label: t('weeklyLabel'), quota: quotas?.weekly, tone: 'text-(--ui-purple)' }
  ]
}

function accountStatus(account, t) {
  if (account.reauth_required) return t ? t('statusReauth') : fallbackT('statusReauth')
  if (account.status === 'dead') return t ? t('statusDead') : fallbackT('statusDead')
  if (account.status === 'cooldown') {
    const minutes = Math.max(1, Math.ceil((Number(account.cooldown || 0) - Date.now() / 1000) / 60))
    if (t) return t('statusCooldown', { m: minutes })
    return fallbackT('statusCooldown', { m: minutes })
  }
  return ''
}

function distinctAccounts(accounts) {
  const byIdentity = new Map()
  for (const account of accounts) {
    const email = String(account?.email || account?.display || '').trim().toLowerCase()
    const plan = String(account?.plan || '').trim().toLowerCase()
    const key = account?.email_verified && email && plan
      ? `${email}\u0000${plan}`
      : `credential\u0000${String(account?.id || '')}`
    const existing = byIdentity.get(key)
    if (!existing || account.current || (!existing.selectable && account.selectable)) {
      byIdentity.set(key, account)
    }
  }
  return [...byIdentity.values()]
}

function QuotaStrip() {
  let t = fallbackT
  try {
    if (typeof usePluginI18n === 'function') {
      const pluginT = usePluginI18n(ID)
      if (pluginT) {
        t = (key, params = {}) => {
          let res = pluginT(key)
          if (!res || res === key) res = fallbackT(key, params)
          else if (typeof res === 'string') {
            for (const [k, v] of Object.entries(params)) {
              res = res.replace(new RegExp(`\\{${k}\\}`, 'g'), String(v))
            }
          }
          return res
        }
      }
    }
  } catch {}

  const [choosing, setChoosing] = useState('')
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: [ID],
    queryFn: () => runStatus(),
    refetchInterval: REFRESH_MS,
    staleTime: 45_000,
    retry: 1
  })
  const data = query.data
  const loading = query.isPending && !data
  const failed = query.isError || (data && !data.available)

  if (loading || failed) {
    return jsx('button', {
      type: 'button',
      onClick: () => void query.refetch(),
      className: cn(
        'inline-flex h-5 items-center gap-1.5 rounded-md px-2 text-[0.6875rem] leading-none',
        'border border-(--ui-stroke-secondary) text-(--ui-text-tertiary)',
        'hover:bg-(--chrome-action-hover) hover:text-foreground'
      ),
      children: failed ? t('unavailable') : t('loading')
    })
  }

  const accounts = data.accounts || []
  const visibleAccounts = distinctAccounts(accounts)
  const current = accounts.find(account => account.current) || null
  const email = current?.email || data.credential?.email || 'Codex'
  const plan = current?.plan || data.plan || ''
  const currentQuotas = {
    session: current?.session ?? data.session,
    weekly: current?.weekly ?? data.weekly,
    monthly: current?.monthly ?? data.monthly
  }
  const currentQuotaSpecs = current?.reauth_required ? [] : quotaSpecsFor(plan, currentQuotas, t)
  const naText = t('na')
  const titleQuotas = currentQuotaSpecs.map(spec => {
    const value = spec.quota?.remaining
    return `${spec.label} ${typeof value === 'number' ? `${value}%` : naText}`
  }).join('｜')
  const title = `${email} · ${plan}${titleQuotas ? `｜${titleQuotas}` : ''}`

  async function selectAccount(account) {
    if (!account?.selectable || account.current || choosing) return
    setChoosing(account.id)
    await queryClient.cancelQueries({ queryKey: [ID] })
    const previous = queryClient.getQueryData([ID])
    queryClient.setQueryData([ID], currentData => {
      if (!currentData) return currentData
      const accounts = (currentData.accounts || []).map(item => ({
        ...item,
        current: item.id === account.id
      }))
      const selected = accounts.find(item => item.id === account.id) || account
      return {
        ...currentData,
        accounts,
        credential: { id: selected.id, email: selected.email, display: selected.display || selected.email },
        plan: selected.plan,
        session: selected.session,
        weekly: selected.weekly,
        monthly: selected.monthly
      }
    })
    try {
      await runStatus(['--select-id', account.id])
      void query.refetch()
      host.notify({
        kind: 'success',
        message: t('successSwitch', { email: account.email })
      })
    } catch (error) {
      queryClient.setQueryData([ID], previous)
      host.notify({ kind: 'error', message: error instanceof Error ? error.message : String(error) })
    } finally {
      setChoosing('')
    }
  }

  return jsx(DropdownMenu, {
    children: [
      jsx(DropdownMenuTrigger, {
        asChild: true,
        children: jsxs('button', {
          type: 'button',
          title,
          style: { minHeight: '2rem', lineHeight: '1.25rem' },
          className: cn(
            'inline-flex min-w-0 max-w-full items-center justify-start gap-1.5 overflow-hidden rounded-md px-3 text-[0.6875rem]',
            'border border-(--ui-stroke-secondary) text-(--ui-text-tertiary)',
            'hover:bg-(--chrome-action-hover) hover:text-foreground'
          ),
          children: [
            jsx('span', { className: 'text-(--ui-accent)', children: '●' }),
            jsx('span', { className: 'min-w-0 truncate whitespace-nowrap font-medium text-foreground', children: email }),
            plan ? jsx('span', { className: 'shrink-0 text-(--ui-text-secondary)', children: `· ${plan}` }) : null,
            jsx('span', { className: 'text-(--ui-text-quaternary)', children: '｜' }),
            ...currentQuotaSpecs.flatMap((spec, index) => [
              index > 0 ? jsx('span', { key: `separator-${spec.key}`, className: 'text-(--ui-text-quaternary)', children: '｜' }) : null,
              quotaLine(spec.label, spec.quota, spec.tone, t, spec.key)
            ]).filter(Boolean),
            jsx('span', { className: 'ml-auto shrink-0 text-(--ui-text-quaternary)', children: '⌄' })
          ]
        })
      }),
      jsx(DropdownMenuContent, {
        align: 'start',
        sideOffset: 4,
        collisionPadding: 8,
        style: MENU_STYLE,
        className: 'min-w-0',
        children: [
          jsx('div', { className: 'px-2 py-1.5 text-xs font-medium text-(--ui-text-secondary)', children: t('selectHeader') }),
          jsx(DropdownMenuSeparator, {}),
          ...visibleAccounts.map(account => {
            const status = accountStatus(account, t)
            const quotaSpecs = account.reauth_required ? [] : quotaSpecsFor(account.plan, account, t)
            return jsx(
              DropdownMenuItem,
              {
                disabled: !account.selectable || account.current || Boolean(choosing),
                onSelect: () => void selectAccount(account),
                className: 'w-full min-w-0',
                children: jsxs('span', {
                  className: 'grid w-full min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] gap-x-2 gap-y-1 py-2',
                  children: [
                    jsx('span', { className: 'w-3 shrink-0', children: account.current ? '✓' : '' }),
                    jsxs('span', { className: 'min-w-0 truncate', children: [jsx('span', { className: 'font-medium', children: account.email || account.display }), jsx('span', { className: 'ml-2 text-(--ui-text-tertiary)', children: account.plan })] }),
                    status ? jsx('span', { className: 'shrink-0 text-(--ui-text-tertiary)', children: status }) : null,
                    quotaSpecs.length ? jsx('span', {
                      className: 'col-start-2 col-span-2 flex flex-wrap gap-x-4 text-xs',
                      children: quotaSpecs.map(spec => quotaLine(spec.label, spec.quota, spec.tone, t, spec.key))
                    }) : null,
                    choosing === account.id ? jsx('span', { className: 'shrink-0', children: '…' }) : null
                  ]
                })
              },
              account.id
            )
          })
        ]
      })
    ]
  })
}

export default {
  id: ID,
  name: 'Codex Account & Quota',
  register(ctx) {
    if (ctx?.i18n?.register) {
      ctx.i18n.register(BUNDLES)
    }
    ctx.register({
      id: 'composer-strip',
      area: COMPOSER_AREAS.underside,
      order: 20,
      render: () => jsx(QuotaStrip, {})
    })
  }
}
