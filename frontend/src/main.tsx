import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

// StrictMode desativado em produção para evitar double-render e logs excessivos
ReactDOM.createRoot(document.getElementById('root')!).render(<App />)
