# Smart Domofon для Home Assistant

Розумний домофон для **координатних** під'їздних домофонів (двопровідна лінія до квартири: Цифрал, Візит, Метаком, СтройМастер…).
ESP8266 стоїть замість (або поряд із) трубкою, бачить дзвінки й уміє відповідати, відчиняти двері чи скидати виклик.

Репозиторій містить:

| Частина | Де | Що робить |
|---|---|---|
| **Прошивка ESPHome** | [`esphome/domofon.yaml`](esphome/domofon.yaml) | Визначення дзвінка, режими, реле, світлодіод, фізична кнопка |
| **Інтеграція HA** (HACS) | [`custom_components/domofon`](custom_components/domofon) | Сповіщення на телефон з кнопками «Відчинити / Скинути», журнал дзвінків, сервіси |
| **Картка Lovelace** | окремий репозиторій [domofon-card](https://github.com/heartpolik/domofon-card) | Статус дзвінка, кнопки, режими, історія |

> [!WARNING]
> Ви підключаєтесь до спільної лінії будинку. Робіть це обережно, не замикайте лінію і не залишайте пристрій у режимі «Завжди відчиняти» без потреби.

## Можливості

- 🔔 Надійне визначення дзвінка: мінімальна тривалість сигналу, одна дія на один дзвінок, ігнорування власних перехідних процесів після дії.
- 🚪 Режими: **Звичайний** · **Відчинити один раз** · **Завжди відчиняти** · **Завжди скидати** (зберігаються після перезавантаження).
- 🧩 **Тип панелі** (налаштування в HA): *Класичний* (як в оригінальному smart-domofon) або *СтройМастер*: див. нижче.
- 📱 Push на iPhone/Android: «Дзвонять у двері» з кнопками **🔓 Відчинити** (з Face ID) та **⛔ Скинути**; потім «Відчинено / Скинуто / Пропущено» замість попереднього сповіщення.
- 📜 Журнал останніх 50 дзвінків (переживає перезапуски), сенсори «Дзвінків сьогодні» та «Останній дзвінок».
- 🛠 Сервіси `domofon.open`, `domofon.reject`, `domofon.release`, `domofon.set_mode` і подія `domofon_call` для автоматизацій.
- ⏱ Усі затримки налаштовуються з HA без перепрошивки.

## Залізо

Схема з оригінального проєкту [Anonym-tsk/smart-domofon](https://github.com/Anonym-tsk/smart-domofon):

- NodeMCU v3 (ESP8266)
- 2 реле: **«відповідь»** (D0) і **«відчинити»** (D1)
- оптопара PC817 через 10 кОм паралельно лінії: детектор дзвінка (D5)
- RGB-світлодіод (D2/D3/D4), кнопка (D6)
- навантаження «трубка знята»: 330 Ом (краще підстроювальний резистор)
- **на клемах трубки (Intercom±): трубка або резистор ~50 Ом**, якщо трубки немає. Без цього панель бачить «немає абонента».

Піни міняються в `substitutions` на початку прошивки.

## Типи панелей

Панелі по-різному трактують «зняти / покласти трубку». Виберіть тип у HA: **Пристрій → Конфігурація → Panel type**.

| | Класичний | СтройМастер |
|---|---|---|
| Відчинити | зняти → імпульс «відчинити» (розрив лінії) → покласти | зняти → покласти (**це вже відкриває двері**) → пауза → зняти → покласти (відпустити лінію) |
| Скинути | зняти → покласти | не відповідати (панель сама завершує виклик) |

На панелі **СтройМастер** (перевірено на реальних дверях) після першого «зняти → покласти» лінія «висить», доки трубку не знімуть і не покладуть ще раз. Тому прошивка робить це автоматично (`Release gap`, 2 с), а для ручного відновлення є кнопка **Release line**.

Якщо ваша панель поводиться інакше, відкрийте issue з описом і логами `Line signal` / `Last event`.

## Встановлення

### 1. Прошивка

1. Скопіюйте [`esphome/domofon.yaml`](esphome/domofon.yaml) в ESPHome Device Builder.
2. Додайте в `secrets.yaml`: `wifi_ssid`, `wifi_password`, `ap_password`, `api_encryption_key` (`openssl rand -base64 32`), `ota_password`.
3. Перевірте піни й `relays_inverted`, прошийте.
4. Додайте пристрій в HA (ESPHome), виберіть **Panel type**.

> Сутності прошивки мають англійські імена (`Mode`, `Open`, `Reject`…), бо інтеграція знаходить їх саме за ними. Перейменовувати в HA можна вільно.

### 2. Інтеграція (HACS)

1. HACS → ⋮ → **Custom repositories** → `https://github.com/heartpolik/ha-domofon`, тип **Integration**.
2. Встановіть **Smart Domofon**, перезапустіть HA.
3. **Налаштування → Пристрої та служби → Додати інтеграцію → Smart Domofon** → виберіть ESPHome-пристрій домофона.
4. **Налаштувати** → виберіть `notify.mobile_app_…` для сповіщень.

### 3. Картка

Див. [domofon-card](https://github.com/heartpolik/domofon-card):

```yaml
type: custom:domofon-card
entity: sensor.domofon_calls_today
```

## Сервіси та події

| Сервіс | Дані |
|---|---|
| `domofon.open` | `config_entry_id` (якщо домофонів кілька) |
| `domofon.reject` | — |
| `domofon.release` | — (⚠️ під час дзвінка на СтройМастер відчинить двері) |
| `domofon.set_mode` | `mode: normal \| open_once \| always_open \| always_reject` |

Подія `domofon_call` (`type: ring | opened | rejected | missed`, `start`, `mode`, `outcome`, `via`) підходить для своїх автоматизацій, наприклад щоб блимати світлом при дзвінку.

## Ліцензія

GPL-3.0. Прошивка є похідною від [Anonym-tsk/smart-domofon](https://github.com/Anonym-tsk/smart-domofon) (GPL-3.0).

---

### English summary

ESPHome firmware + Home Assistant integration for coordinate (two-wire) apartment intercoms. Features: reliable call detection, four modes, per-panel open/reject logic (classic and *StroyMaster*), actionable phone notifications (Open / Reject), call log sensors and services. Install the firmware from `esphome/`, then add this repo to HACS as a custom *Integration* repository. Lovelace card: [domofon-card](https://github.com/heartpolik/domofon-card).
