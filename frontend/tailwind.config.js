/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // Calm light surfaces + slate ink
        canvas: '#f7f9fc',
        surface: '#ffffff',
        ink: {
          900: '#0f172a',
          700: '#334155',
          500: '#64748b',
          400: '#94a3b8',
          300: '#cbd5e1',
        },
        line: '#eef2f7',
        // Accents — soft, eye-soothing
        indigo: {
          50: '#eef2ff', 100: '#e0e7ff', 200: '#c7d2fe', 300: '#a5b4fc',
          400: '#818cf8', 500: '#6366f1', 600: '#4f46e5', 700: '#4338ca',
        },
        teal: {
          50: '#f0fdfa', 100: '#ccfbf1', 300: '#5eead4', 500: '#14b8a6', 600: '#0d9488',
        },
        violet: { 100: '#ede9fe', 400: '#a78bfa', 500: '#8b5cf6', 600: '#7c3aed' },
        emerald: { 50: '#ecfdf5', 100: '#d1fae5', 500: '#10b981', 600: '#059669' },
        amber: { 50: '#fffbeb', 100: '#fef3c7', 500: '#f59e0b', 600: '#d97706' },
        rose: { 50: '#fff1f2', 100: '#ffe4e6', 500: '#f43f5e', 600: '#e11d48' },
        sky: { 50: '#f0f9ff', 100: '#e0f2fe', 500: '#0ea5e9', 600: '#0284c7' },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"Fira Code"', 'ui-monospace', 'monospace'],
      },
      borderRadius: {
        xl: '0.875rem',
        '2xl': '1.125rem',
        '3xl': '1.5rem',
      },
      boxShadow: {
        soft: '0 1px 2px rgba(16,24,40,0.04), 0 12px 32px -12px rgba(16,24,40,0.10)',
        lift: '0 2px 4px rgba(16,24,40,0.05), 0 20px 48px -16px rgba(79,70,229,0.18)',
        ring: '0 0 0 1px rgba(15,23,42,0.04)',
      },
      keyframes: {
        floaty: {
          '0%,100%': { transform: 'translate(0,0) scale(1)' },
          '50%': { transform: 'translate(14px,-18px) scale(1.05)' },
        },
        shimmer: {
          '0%': { backgroundPosition: '0% 50%' },
          '100%': { backgroundPosition: '200% 50%' },
        },
        pulseSoft: {
          '0%,100%': { opacity: '1' },
          '50%': { opacity: '0.45' },
        },
      },
      animation: {
        floaty: 'floaty 18s ease-in-out infinite',
        shimmer: 'shimmer 2.5s linear infinite',
        pulseSoft: 'pulseSoft 2s ease-in-out infinite',
      },
    },
  },
  plugins: [],
};
