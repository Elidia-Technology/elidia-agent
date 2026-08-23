import js from '@eslint/js'
import typescriptEslint from '@typescript-eslint/eslint-plugin'
import typescriptParser from '@typescript-eslint/parser'
import perfectionist from 'eslint-plugin-perfectionist'
import reactPlugin from 'eslint-plugin-react'
import reactCompiler from 'eslint-plugin-react-compiler'
import hooksPlugin from 'eslint-plugin-react-hooks'
import unusedImports from 'eslint-plugin-unused-imports'
import globals from 'globals'

const noopRule = {
  meta: { schema: [], type: 'problem' },
  create: () => ({})
}

const customRules = {
  rules: {
    'no-process-cwd': noopRule,
    'no-process-env-top-level': noopRule,
    'no-sync-fs': noopRule,
    'no-top-level-dynamic-import': noopRule,
    'no-top-level-side-effects': noopRule
  }
}

export default [
  {
    // `build/` and `release/` are electron-builder OUTPUT. They vendor
    // node-pty's own sources and tests, which account for 564 of the 672
    // errors this config reported — third-party bundled JS, linted as if it
    // were ours. With --max-warnings=0 the gate could never pass, so it was
    // effectively dead: nobody can act on a report that is 84% build artifacts.
    // Same omission the vitest config had for `release/`.
    ignores: [
      '**/node_modules/**',
      '**/dist/**',
      'build/**',
      'release/**',
      'src/**/*.js'
    ]
  },
  js.configs.recommended,
  {
    rules: {
      // `try { fs.unlinkSync(tmp) } catch {}` before rejecting with the real
      // error is correct: a failed cleanup must not mask the failure the caller
      // actually needs. 17 of these are best-effort cleanup in bootstrap-runner.
      'no-empty': ['error', { allowEmptyCatch: true }],
      // `const { kind, t: _t, ...rest } = e` discards a field on purpose. The
      // underscore prefix is the convention for that; without this the linter
      // reports an intentional discard as dead code.
      'no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }]
    }
  },
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node
      },
      parser: typescriptParser,
      parserOptions: {
        ecmaFeatures: { jsx: true },
        ecmaVersion: 'latest',
        sourceType: 'module'
      }
    },
    plugins: {
      '@typescript-eslint': typescriptEslint,
      'custom-rules': customRules,
      perfectionist,
      react: reactPlugin,
      'react-compiler': reactCompiler,
      'react-hooks': hooksPlugin,
      'unused-imports': unusedImports
    },
    rules: {
      '@typescript-eslint/consistent-type-imports': ['error', { prefer: 'type-imports' }],
      '@typescript-eslint/no-unused-vars': 'off',
      curly: ['error', 'all'],
      'no-fallthrough': ['error', { allowEmptyCase: true }],
      'no-undef': 'off',
      'no-unused-vars': 'off',
      'padding-line-between-statements': [
        1,
        {
          blankLine: 'always',
          next: [
            'block-like',
            'block',
            'return',
            'if',
            'class',
            'continue',
            'debugger',
            'break',
            'multiline-const',
            'multiline-let'
          ],
          prev: '*'
        },
        {
          blankLine: 'always',
          next: '*',
          prev: ['case', 'default', 'multiline-const', 'multiline-let', 'multiline-block-like']
        },
        { blankLine: 'never', next: ['block', 'block-like'], prev: ['case', 'default'] },
        { blankLine: 'always', next: ['block', 'block-like'], prev: ['block', 'block-like'] },
        { blankLine: 'always', next: ['empty'], prev: 'export' },
        { blankLine: 'never', next: 'iife', prev: ['block', 'block-like', 'empty'] }
      ],
      'perfectionist/sort-exports': ['error', { order: 'asc', type: 'natural' }],
      'perfectionist/sort-imports': [
        'error',
        {
          groups: ['side-effect', 'builtin', 'external', 'internal', 'parent', 'sibling', 'index'],
          order: 'asc',
          type: 'natural'
        }
      ],
      'perfectionist/sort-jsx-props': ['error', { order: 'asc', type: 'natural' }],
      'perfectionist/sort-named-exports': ['error', { order: 'asc', type: 'natural' }],
      'perfectionist/sort-named-imports': ['error', { order: 'asc', type: 'natural' }],
      'react-compiler/react-compiler': 'warn',
      'react-hooks/exhaustive-deps': 'warn',
      'react-hooks/rules-of-hooks': 'error',
      'unused-imports/no-unused-imports': 'error'
    },
    settings: {
      react: { version: 'detect' }
    }
  },
  {
    files: ['**/*.js', '**/*.cjs'],
    ignores: ['**/node_modules/**', '**/dist/**', 'build/**', 'release/**'],
    languageOptions: {
      ecmaVersion: 'latest',
      globals: { ...globals.node },
      sourceType: 'commonjs'
    }
  },
  {
    // ESM Node scripts (scripts/*.mjs). There was no block for .mjs at all, so
    // they inherited no globals and every console/process/setTimeout/fetch read
    // as undefined — 252 no-undef errors that were pure config, not code.
    // `globals.browser` is included for fetch/WebSocket/setTimeout, which these
    // scripts use against a running dashboard and which modern Node provides.
    files: ['**/*.mjs'],
    ignores: ['**/node_modules/**', '**/dist/**', 'build/**', 'release/**'],
    languageOptions: {
      ecmaVersion: 'latest',
      globals: { ...globals.node, ...globals.browser },
      sourceType: 'module'
    }
  },
  {
    ignores: ['*.config.*']
  }
]
