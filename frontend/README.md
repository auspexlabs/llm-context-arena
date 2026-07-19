# Curia Observatory

The Observatory is Curia's watch-first browser interface. It is a small TypeScript/Vite application with no component framework; the source lives under `src/deck/`.

```bash
npm install
npm run dev       # http://localhost:5173
npm run build     # type-check and produce dist/
```

By default the browser calls the Curia API at `http://localhost:8001`. Set `VITE_API_BASE` when the backend is exposed elsewhere.

Architecture and interaction decisions belong in `../docs/decision_log.md`; the current control-plane/UI status is tracked in `../docs/piv-001-checklist.md`.
