import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

// Este app nunca registrou service worker — mas o browser pode ter um antigo
// de outro projeto testado na mesma origem (localhost), ainda interceptando
// fetches com lógica desatualizada (achado durante teste local: request de
// thumbnail saindo com querystring de uma versão que nunca existiu aqui).
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.getRegistrations().then((regs) => {
    regs.forEach((reg) => reg.unregister())
  })
}

// StrictMode desativado em produção para evitar double-render e logs excessivos
ReactDOM.createRoot(document.getElementById('root')!).render(<App />)
