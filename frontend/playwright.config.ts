import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [['html', { outputFolder: 'tests/e2e/report' }], ['list']],

  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    // data-testid como seletor padrão
    testIdAttribute: 'data-testid',
  },

  projects: [
    // Desktop Chrome — obrigatório
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },

    // Mobile — verifica responsividade
    {
      name: 'mobile',
      use: { ...devices['Pixel 7'] },
      // Rodar somente telas críticas no mobile
      testMatch: ['**/auth.spec.ts', '**/cameras.spec.ts'],
    },
  ],

  // Subir o Vite dev server antes dos testes
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 60000,
  },
})
