import { useState } from 'react'
import { Save } from 'lucide-react'
import toast from 'react-hot-toast'

export function AdminSettingsPage() {
  const [tab, setTab] = useState<'platform' | 'smtp'>('platform')
  const [platform, setPlatform] = useState({ name: 'VMS', primary_color: '#3b82f6' })
  const [smtp, setSmtp] = useState({ host: '', port: 587, user: '', password: '', tls: true, sender: '' })

  const handleSavePlatform = () => toast.success('Configurações da plataforma salvas')
  const handleSaveSMTP = () => toast.success('Configurações SMTP salvas')

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-bold text-white">Configurações da Plataforma</h1>

      <div className="flex gap-1 border-b border-gray-700">
        {(['platform', 'smtp'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium transition-colors ${tab === t ? 'text-blue-400 border-b-2 border-blue-400' : 'text-gray-400 hover:text-gray-300'}`}
          >
            {t === 'platform' ? 'Plataforma' : 'SMTP'}
          </button>
        ))}
      </div>

      {tab === 'platform' && (
        <div className="bg-gray-800 rounded-lg p-6 space-y-4 max-w-lg">
          <div>
            <label className="block text-sm text-gray-400 mb-1">Nome do Sistema</label>
            <input value={platform.name} onChange={e => setPlatform(p => ({ ...p, name: e.target.value }))}
              className="w-full bg-gray-700 text-white rounded-lg px-3 py-2 text-sm border border-gray-600 outline-none" />
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">Cor Primária</label>
            <div className="flex items-center gap-3">
              <input type="color" value={platform.primary_color} onChange={e => setPlatform(p => ({ ...p, primary_color: e.target.value }))}
                className="w-10 h-10 rounded cursor-pointer bg-transparent border-0" />
              <input value={platform.primary_color} onChange={e => setPlatform(p => ({ ...p, primary_color: e.target.value }))}
                className="flex-1 bg-gray-700 text-white rounded-lg px-3 py-2 text-sm border border-gray-600 outline-none font-mono" />
            </div>
          </div>
          <button onClick={handleSavePlatform} className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-medium">
            <Save size={14} /> Salvar
          </button>
        </div>
      )}

      {tab === 'smtp' && (
        <div className="bg-gray-800 rounded-lg p-6 space-y-4 max-w-lg">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm text-gray-400 mb-1">Host SMTP</label>
              <input value={smtp.host} onChange={e => setSmtp(s => ({ ...s, host: e.target.value }))}
                placeholder="smtp.gmail.com"
                className="w-full bg-gray-700 text-white rounded-lg px-3 py-2 text-sm border border-gray-600 outline-none" />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Porta</label>
              <input type="number" value={smtp.port} onChange={e => setSmtp(s => ({ ...s, port: +e.target.value }))}
                className="w-full bg-gray-700 text-white rounded-lg px-3 py-2 text-sm border border-gray-600 outline-none" />
            </div>
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">Usuário</label>
            <input value={smtp.user} onChange={e => setSmtp(s => ({ ...s, user: e.target.value }))}
              className="w-full bg-gray-700 text-white rounded-lg px-3 py-2 text-sm border border-gray-600 outline-none" />
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">Senha</label>
            <input type="password" value={smtp.password} onChange={e => setSmtp(s => ({ ...s, password: e.target.value }))}
              className="w-full bg-gray-700 text-white rounded-lg px-3 py-2 text-sm border border-gray-600 outline-none" />
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">Email Remetente</label>
            <input type="email" value={smtp.sender} onChange={e => setSmtp(s => ({ ...s, sender: e.target.value }))}
              className="w-full bg-gray-700 text-white rounded-lg px-3 py-2 text-sm border border-gray-600 outline-none" />
          </div>
          <div className="flex items-center gap-2">
            <input type="checkbox" checked={smtp.tls} onChange={e => setSmtp(s => ({ ...s, tls: e.target.checked }))} id="tls" />
            <label htmlFor="tls" className="text-sm text-gray-300">Usar TLS</label>
          </div>
          <button onClick={handleSaveSMTP} className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-medium">
            <Save size={14} /> Salvar
          </button>
        </div>
      )}
    </div>
  )
}
