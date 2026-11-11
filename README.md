# Хими цэвэрлэгээний үйлчилгээний систем

![Python CI](https://github.com/<OWNER>/<REPO>/actions/workflows/ci.yml/badge.svg)

> `<OWNER>/<REPO>`-г өөрийн GitHub репозиторын нэрээр солино.

Sprint 1-ийн хэрэгжилт:

- **US-05** — үйлчлүүлэгч өөрийн захиалгын хувцас, төлөв, баталгаажсан хугацаа, шинэчлэлтийн түүхийг харна.
- **US-04** — цэвэрлэгээний ажилтан зөвшөөрөгдсөн дарааллаар захиалгын төлөвийг шинэчилнэ.

Python 3.10+ стандарт сан, SQLite. Тестэд зөвхөн `pytest` хэрэгтэй.

## Бүтэц

```
himi-tseverlegee/
├── src/
│   ├── app.py          # HTTP сервер, API, нэвтрэлт, өгөгдлийн сан
│   ├── workflow.py     # төлөвийн шилжилтийн дүрэм (цэвэр функц)
│   └── static/         # index.html, app.js, style.css
├── tests/
│   ├── test_workflow.py  # төлөвийн дүрмийн unit тест
│   └── test_api.py       # бодит HTTP сервер дээрх TC01–TC24
├── docs/DEFINITION_OF_DONE.md
├── requirements.txt
├── pytest.ini
└── .github/workflows/ci.yml
```

## Ажиллуулах

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export LAB5_DEMO_PASSWORD='10+тэмдэгттэй-нууц-үг'   # Windows PowerShell: $env:LAB5_DEMO_PASSWORD='...'
python -m src.app --init           # нэг удаа: data/himi.db үүсгэнэ
python -m src.app                  # http://127.0.0.1:8000
```

Туршилтын хэрэглэгчид (бүгд `LAB5_DEMO_PASSWORD` нууц үгтэй): `nomin` (HC-0001, HC-0003), `bat` (HC-0002), `empty` (захиалгагүй), `worker` (цэвэрлэгээний ажилтан).

## Тест

```bash
python -m pytest -v
```

42 тест: төлөвийн дүрмийн 18 unit тест + API/аюулгүй байдлын 24 тест (TC01–TC24).

## API

| Хүсэлт | Үр дүн |
|---|---|
| `POST /api/login` | Session cookie, role, CSRF token |
| `GET /api/orders` | Өөрийн захиалгууд эсвэл ажилтны ажлын жагсаалт |
| `GET /api/orders/{id}` | Хувцас, төлөв, хугацаа, явц (%), түүх |
| `POST /api/orders/{id}/status` | Ажилтны төлөв шинэчлэлт (`X-CSRF-Token` шаардлагатай) |
| `POST /api/logout` | Session хүчингүй болно |

Алдааны код: 400 буруу оролт · 401 нэвтрэлт · 403 эрх/CSRF · 404 олдоогүй эсвэл хандах эрхгүй.

## Тасралтгүй интеграцчилал (CI)

`.github/workflows/ci.yml` нь `push` болон `main` руу чиглэсэн `pull_request` бүрд GitHub Actions дээр ажиллана:

1. Кодыг татах (`actions/checkout@v4`)
2. Python 3.10 ба 3.12 орчин бэлтгэх (`actions/setup-python@v5`)
3. `requirements.txt`-ээс хамаарал суулгах
4. Build: `compileall`-аар синтакс шалгах, `--init`-ээр өгөгдлийн сан үүсгэх
5. `pytest`-ээр бүх тест ажиллуулах
6. Тестийн үр дүнг (`test-results.xml`) artifact болгон хадгалах

Ажлын дүрэм:

- `main` салбарт шууд push хийхгүй; шинэ ажлыг `feature/...` салбарт хийж pull request нээнэ.
- CI ногоон (✓) болж, багийн нэг гишүүн хянасны дараа л merge хийнэ.
- CI улаан (✗) бол Actions → алдаатай job → log-ийг уншиж, засаад дахин push хийнэ.

GitHub дээр тохируулах (Settings → Branches → Add rule → `main`): *Require a pull request before merging*, *Require status checks to pass* → `Build ба тест (Python 3.10)`, `Build ба тест (Python 3.12)`.

## Хязгаар

Сургалтын зорилгоор 127.0.0.1 дээр ажиллана. Production-д HTTPS, Secure cookie, login rate limiting, production сервер шаардлагатай.
