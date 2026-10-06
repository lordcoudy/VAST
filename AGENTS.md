# AGENTS.md

## Spec-Driven Development (OpenSpec)

Этот репозиторий подключает OpenSpec (`openspec/`, schema `spec-driven`). Регламент применяется автоматически: разработка начинается со спеки, не с кода.

Одна задача = одна ветка = один Merge Request:

```
спека → Draft MR → ревью спеки → реализация в том же MR → проверки в CI → archive → финальное ревью → merge
```

### Запреты

- Не писать production-код, тесты и правки CI до одобрения спеки ревьюером в MR (с указанием рассмотренного коммита).
- Не подгонять спеку под уже написанный код без повторного ревью.
- Не сливать MR без закоммиченного `archive` в этой же ветке.
- Не оставлять архив только локально.
- Не менять имя изменения OpenSpec внутри одного MR.

Запрос «сделай / реализуй / почини X» без одобренного изменения — это запрос на спеку. Создай документы, остановись.

### Команды и skills

Одно kebab-case имя изменения на весь MR (например `add-report-export`). При новом чате называй это имя: документы в `openspec/changes/<name>/` — полный контекст.

| Действие | Claude Code | Codex | Grok skill |
|---|---|---|---|
| Обсудить идею | `/opsx:explore <name>` | `$openspec-explore` | `openspec-explore` |
| Создать документы | `/opsx:propose <name>` | `$openspec-propose` | `openspec-propose` |
| Исправить документы | `/opsx:update <name>` | `$openspec-update-change` | `openspec-update-change` |
| Реализовать | `/opsx:apply <name>` | `$openspec-apply-change` | `openspec-apply-change` |
| Sync без archive | `/opsx:sync <name>` | `$openspec-sync-specs` | `openspec-sync-specs` |
| Archive | `/opsx:archive <name>` | `$openspec-archive-change` | `openspec-archive-change` |

Перед выполнением прочитай соответствующий `SKILL.md` в `.agents/skills/` или `.claude/skills/`.

Автовыбор: идея → explore; новая задача → propose и стоп; замечания к спеке → update, код не трогать; «спека одобрена» → apply; готовность к merge → archive и подтвердить sync дельт в `openspec/specs/`.

### Артефакты

`openspec/changes/<change-name>/`: `proposal.md`, `specs/`, `design.md`, `tasks.md`. Основные спеки: `openspec/specs/`.

Перед ревью спеки должны быть ясны: границы, поведение, ошибки и граничные случаи, ограничения, критерии приёмки.

Draft MR: имя изменения, ссылка на каталог, цель, этап «Ревью спеки», критерии приёмки.

### Реализация и archive

После одобрения спеки работай строго по согласованным документам. Код, тесты и `tasks.md` — в ту же ветку. Если требования сломались — сначала update документов и повторное ревью.

Перед merge обязателен archive в этой же ветке. Подтверди перенос дельт в `openspec/specs/`. Каталог изменения должен оказаться в `openspec/changes/archive/YYYY-MM-DD-<change-name>/`, результат — закоммичен в тот же MR.

Чек-лист merge: ревью спеки до кода; согласованные правки требований; задачи и тесты; CI соответствия; разобранные предупреждения; закоммиченный archive; зелёный последний коммит; финальное одобрение.
