/// <reference types="vite/client" />

// Without this, importing an image is a type error: TypeScript has no idea
// what `import banner from './banner.png'` yields. Vite's client types declare
// those module shapes. The desktop app carries the identical file; mobile
// simply never imported an asset before.
