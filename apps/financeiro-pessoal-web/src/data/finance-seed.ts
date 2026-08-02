export type MoneySource = 'mock' | 'seed-candidato' | 'confirmado'
export type Actor = 'William' | 'Erika' | 'Hermes' | 'Integração automática'

export interface Metric {
  label: string
  value: string
  helper: string
  tone?: 'green' | 'yellow' | 'red' | 'blue' | 'purple'
}

export interface Category {
  id: string
  name: string
  group: string
  examples: string[]
}

export interface FinancialDestination {
  id: string
  name: string
  categoryId: string
  category: string
  planned: number
  spent: number
  status: 'sobrando' | 'estourado' | 'reservado' | 'sem-destino'
  owner: Actor
}

export interface MonthlyItem {
  id: string
  month: string
  date: string
  description: string
  person: Actor
  categoryId: string
  category: string
  destination: string
  institution: string
  planned: number
  realized: number
  status: 'Planejado' | 'Pago' | 'Pendente' | 'Acima do planejado' | 'Sem destino' | 'A revisar'
  origin: 'Manual demo' | 'Automática' | 'Hermes' | 'WhatsApp' | 'OCR'
  action: string
}

export interface Decision {
  title: string
  context: string
  suggestion: string
  impact: string
  status: string
}

export interface Reserve {
  name: string
  current: number
  target: number
  location: string
  priority: string
}

export interface Transaction {
  date: string
  description: string
  category: string
  destination: string
  institution: string
  type: string
  value: string
  origin: string
  link: string
}

export const financeSeedMetadata = {
  version: 'seed-prototype-v0.2',
  source: 'mock',
  purpose: 'Protótipo navegável e base para transformar dados em linguagem natural no seed inicial reaproveitável.',
  canonicalUrl: 'https://minhasfinancas.prosperfy.com.br/',
  lastUpdated: '2026-08-02',
} as const

export const categories: Category[] = [
  { id: 'moradia', name: 'Moradia', group: 'Essenciais', examples: ['Aluguel', 'Condomínio', 'Energia', 'Internet'] },
  { id: 'mercado', name: 'Mercado', group: 'Essenciais', examples: ['Supermercado', 'Farmácia recorrente', 'Itens de casa'] },
  { id: 'transporte', name: 'Transporte', group: 'Essenciais', examples: ['Gasolina', 'Uber', 'Estacionamento'] },
  { id: 'criancas', name: 'Crianças', group: 'Família', examples: ['Escola', 'Material escolar', 'Farmácia infantil'] },
  { id: 'saude', name: 'Saúde', group: 'Essenciais', examples: ['Farmácia', 'Consulta', 'Plano de saúde'] },
  { id: 'lazer', name: 'Lazer', group: 'Variáveis', examples: ['Restaurante', 'Passeios', 'Streaming'] },
  { id: 'dividas', name: 'Dívidas e Empréstimos', group: 'Compromissos', examples: ['Parcela de empréstimo', 'Acordos'] },
  { id: 'reservas', name: 'Reservas e Metas', group: 'Planejamento', examples: ['Emergência', 'TV', 'Material escolar'] },
  { id: 'sem-categoria', name: 'Sem categoria', group: 'Triagem', examples: ['Item novo aguardando classificação'] },
]

export const metrics: Metric[] = [
  { label: 'Saldo atual', value: 'R$ 8.420', helper: 'Dinheiro disponível hoje nas instituições', tone: 'green' },
  { label: 'Valores a receber', value: 'R$ 1.230', helper: 'Projeção, não disponível agora', tone: 'blue' },
  { label: 'Após recebimentos', value: 'R$ 9.650', helper: 'Saldo projetado se tudo for pago', tone: 'blue' },
  { label: 'Total reservado', value: 'R$ 4.800', helper: 'Dinheiro com finalidade definida', tone: 'purple' },
  { label: 'Saldo livre', value: 'R$ 1.140', helper: 'Livre após reservas e compromissos', tone: 'green' },
  { label: 'Déficits', value: 'R$ 250', helper: 'A compensar em decisões futuras', tone: 'red' },
  { label: 'Faturas abertas', value: 'R$ 2.180', helper: 'Cartões de agosto', tone: 'yellow' },
  { label: 'Empréstimos', value: 'R$ 6.400', helper: 'Saldo restante fictício', tone: 'red' },
]

export const financialDestinations: FinancialDestination[] = [
  { id: 'aluguel-agosto', name: 'Aluguel Agosto', categoryId: 'moradia', category: 'Moradia', planned: 2200, spent: 2200, status: 'sobrando', owner: 'William' },
  { id: 'mercado-agosto', name: 'Mercado de agosto', categoryId: 'mercado', category: 'Mercado', planned: 1400, spent: 1095, status: 'sobrando', owner: 'Erika' },
  { id: 'gasolina-agosto', name: 'Gasolina de agosto', categoryId: 'transporte', category: 'Transporte', planned: 600, spent: 450, status: 'sobrando', owner: 'William' },
  { id: 'criancas-agosto', name: 'Crianças de agosto', categoryId: 'criancas', category: 'Crianças', planned: 900, spent: 930, status: 'estourado', owner: 'Erika' },
  { id: 'extras-agosto', name: 'Extras', categoryId: 'lazer', category: 'Lazer', planned: 500, spent: 300, status: 'sobrando', owner: 'William' },
  { id: 'reserva-tv', name: 'Reserva TV', categoryId: 'reservas', category: 'Reservas e Metas', planned: 250, spent: 0, status: 'reservado', owner: 'William' },
]

export const monthlyItems: MonthlyItem[] = [
  { id: 'item-aluguel', month: '2026-08', date: '05/08', description: 'Aluguel', person: 'William', categoryId: 'moradia', category: 'Moradia', destination: 'Aluguel Agosto', institution: 'Nubank', planned: 2200, realized: 2200, status: 'Pago', origin: 'Manual demo', action: 'Ver comprovante' },
  { id: 'item-pague-menos', month: '2026-08', date: '02/08', description: 'Pague Menos', person: 'Erika', categoryId: 'saude', category: 'Saúde', destination: 'Mercado de agosto', institution: 'Nubank', planned: 470, realized: 580, status: 'Acima do planejado', origin: 'OCR', action: 'Abrir decisão' },
  { id: 'item-supermercado', month: '2026-08', date: '02/08', description: 'Supermercado Vitória', person: 'Erika', categoryId: 'mercado', category: 'Mercado', destination: 'Mercado de agosto', institution: 'C6', planned: 345, realized: 345, status: 'Pago', origin: 'Automática', action: 'Classificado' },
  { id: 'item-gasolina', month: '2026-08', date: '03/08', description: 'Posto Shell', person: 'William', categoryId: 'transporte', category: 'Transporte', destination: 'Gasolina de agosto', institution: 'Nubank', planned: 250, realized: 250, status: 'Pago', origin: 'Automática', action: 'Classificado' },
  { id: 'item-escola', month: '2026-08', date: '07/08', description: 'Material escolar', person: 'Erika', categoryId: 'criancas', category: 'Crianças', destination: 'Crianças de agosto', institution: 'C6', planned: 300, realized: 330, status: 'Acima do planejado', origin: 'Manual demo', action: 'Revisar destino' },
  { id: 'item-sem-destino', month: '2026-08', date: '08/08', description: 'Compra não prevista', person: 'William', categoryId: 'sem-categoria', category: 'Sem categoria', destination: 'Sem destino planejado', institution: 'Nubank', planned: 0, realized: 600, status: 'Sem destino', origin: 'Automática', action: 'Enviar para decisão' },
  { id: 'item-tv', month: '2026-08', date: '10/08', description: 'Parcela TV sala', person: 'William', categoryId: 'reservas', category: 'Reservas e Metas', destination: 'Reserva TV', institution: 'Nubank Cartão', planned: 180, realized: 180, status: 'Planejado', origin: 'Automática', action: 'Vinculado' },
]

export const decisions: Decision[] = [
  {
    title: 'Gasto não previsto de R$ 600',
    context: 'Saída sem destino planejado detectada em Agosto/2026.',
    suggestion: 'Usar R$ 200 de Extras + R$ 150 de Gasolina e manter R$ 250 como déficit.',
    impact: 'Déficit cai de R$ 600 para R$ 250; reservas não são tocadas.',
    status: 'Aguardando William',
  },
  {
    title: 'Categoria Crianças estourada em R$ 30',
    context: 'Gasto realizado R$ 930 contra R$ 900 planejados.',
    suggestion: 'Transferir R$ 30 de Extras para Crianças, se William autorizar.',
    impact: 'Mostra origem, destino, justificativa, confirmação e histórico.',
    status: 'Simulação',
  },
  {
    title: 'Nota Pague Menos aguardando confirmação',
    context: 'OCR identificou total de R$ 580 e rateio com terceiros.',
    suggestion: 'Confirmar Mercado R$ 345, Crianças R$ 125, Elisa R$ 55 e Edi R$ 55.',
    impact: 'Gasto familiar fica R$ 470; contas a receber somam R$ 110.',
    status: 'Pendente Erika/William',
  },
]

export const reserves: Reserve[] = [
  { name: 'Emergência', current: 3000, target: 10000, location: 'Nubank R$ 1.800 • C6 R$ 1.000 • físico R$ 200', priority: 'Alta' },
  { name: 'TV', current: 900, target: 2500, location: 'Nubank R$ 600 • C6 R$ 200 • físico R$ 100', priority: 'Média' },
  { name: 'Presente da Erika', current: 500, target: 800, location: 'C6 R$ 500', priority: 'Média' },
  { name: 'Material escolar', current: 400, target: 1200, location: 'Nubank R$ 400', priority: 'Alta' },
]

export const transactions: Transaction[] = [
  { date: '02/08', description: 'Pague Menos', category: 'Saúde', destination: 'Mercado de agosto', institution: 'Nubank', type: 'Saída', value: 'R$ 580', origin: 'Automática/OCR', link: 'Nota vinculada' },
  { date: '02/08', description: 'Supermercado Vitória', category: 'Mercado', destination: 'Mercado de agosto', institution: 'C6', type: 'Saída', value: 'R$ 345', origin: 'Automática', link: 'Sem comprovante' },
  { date: '01/08', description: 'Salário fictício', category: 'Receita', destination: 'Saldo livre projetado', institution: 'Bradesco', type: 'Entrada', value: 'R$ 7.000', origin: 'Manual demo', link: 'Previsto' },
  { date: '31/07', description: 'Compra cartão — TV', category: 'Reservas e Metas', destination: 'Reserva TV', institution: 'Nubank Cartão', type: 'Cartão', value: 'R$ 180', origin: 'Automática', link: 'Parcela 3/10' },
]

export const receivables = [
  { person: 'Elisa', reason: 'Rateio nota Pague Menos', total: 'R$ 55', received: 'R$ 0', remaining: 'R$ 55', status: 'A receber' },
  { person: 'Edi', reason: 'Rateio nota Pague Menos', total: 'R$ 55', received: 'R$ 0', remaining: 'R$ 55', status: 'A receber' },
  { person: 'Lucas', reason: 'Compra familiar fictícia', total: 'R$ 1.120', received: 'R$ 0', remaining: 'R$ 1.120', status: 'Previsto' },
]

export const loans = [
  { creditor: 'Empréstimo familiar fictício', received: 'R$ 8.000', total: 'R$ 8.800', paid: 'R$ 2.400', remaining: 'R$ 6.400', installment: 'R$ 800', next: '10/08/2026' },
]

export const cardBills = [
  { card: 'Nubank William', limit: 'R$ 8.000', current: 'R$ 1.420', next: 'R$ 980', status: 'Sincronizado' },
  { card: 'C6 Erika', limit: 'R$ 5.000', current: 'R$ 760', next: 'R$ 410', status: 'Pendente revisão' },
]

export const cardPurchases = [
  { purchase: 'TV sala', card: 'Nubank William', category: 'Reservas e Metas', installment: '3/10', value: 'R$ 180', link: 'Reserva TV' },
  { purchase: 'Farmácia', card: 'C6 Erika', category: 'Saúde', installment: '1/1', value: 'R$ 89', link: 'Crianças de agosto' },
  { purchase: 'Mercado', card: 'Nubank William', category: 'Mercado', installment: '1/1', value: 'R$ 345', link: 'Mercado agosto' },
]

export const documents = [
  { name: 'Nota Pague Menos', origin: 'WhatsApp Erika', total: 'R$ 580', confidence: '87%', status: 'Aguardando confirmação', split: 'Mercado R$ 345 • Crianças R$ 125 • Elisa R$ 55 • Edi R$ 55' },
  { name: 'Comprovante mercado', origin: 'Upload William', total: 'R$ 345', confidence: '72%', status: 'OCR baixa confiança', split: 'A revisar' },
]

export const integrations = [
  { name: 'Pluggy sandbox', kind: 'Open Finance', status: 'POC aprovada', sync: '00:12', next: 'Manual no protótipo' },
  { name: 'Nubank', kind: 'Banco', status: 'Representado', sync: 'Dados fictícios', next: 'Produção futura' },
  { name: 'C6', kind: 'Banco', status: 'Pendente futuro', sync: '—', next: 'Não conectar agora' },
  { name: 'WhatsApp', kind: 'Canal', status: 'Representado', sync: 'Simulado', next: 'Integração futura' },
]
