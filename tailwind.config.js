/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./templates/**/*.html', './static/**/*.js'],
  theme: {
    extend: {
      colors: {
        cyberCyan: '#06B6D4',
        neonEmerald: '#10B981',
        darkCanvas: '#05070c',
        darkBg: '#090d16',
        darkCard: 'rgba(255, 255, 255, 0.03)',
        borderGlass: 'rgba(255, 255, 255, 0.08)',
      },
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
        outfit: ['Outfit', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
