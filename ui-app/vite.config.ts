import path from "path"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "./",
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  build: { outDir: "../ui/dist", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:7777" } },
})
