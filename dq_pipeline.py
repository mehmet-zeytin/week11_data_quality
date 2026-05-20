import sys
import pandas as pd
import great_expectations as gx
import requests
import json
from pydantic import BaseModel, field_validator, ValidationError
from datetime import datetime
 
# ============================================================
# AYARLAR
# ============================================================
 
CSV_PATH = "data/amazon_orders.csv"
VALID_OUTPUT   = "data/valid_rows.csv"
INVALID_OUTPUT = "data/invalid_rows.csv"
ALLOWED_STATUSES = ["Shipped", "Delivered", "Cancelled", "Pending", "Returned"]
 
# Slack webhook — GitHub Secrets'tan veya direkt girilebilir
import os
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
 
# ============================================================
# SLACK BİLDİRİMİ
# ============================================================
 
def send_slack(message):
    if not SLACK_WEBHOOK_URL:
        print("⚠️  SLACK_WEBHOOK_URL tanımlı değil, bildirim atlandı.")
        return
    try:
        response = requests.post(
            SLACK_WEBHOOK_URL,
            data=json.dumps({"text": message}),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if response.status_code == 200:
            print("✅ Slack bildirimi gönderildi.")
        else:
            print(f"⚠️  Slack gönderilemedi. Status: {response.status_code}")
    except Exception as e:
        print(f"⚠️  Slack bağlantı hatası: {e}")
 
# ============================================================
# VERİYİ YÜKLE
# ============================================================
 
print("=" * 60)
print("📂 Veri yükleniyor...")
print("=" * 60)
 
df = pd.read_csv(CSV_PATH)
print(f"✅ Veri yüklendi. Satır: {len(df)}, Kolon: {list(df.columns)}")
print()
 
# ============================================================
# BÖLÜM 1 — GREAT EXPECTATIONS VALİDASYONU
# ============================================================
 
print("=" * 60)
print("🔍 BÖLÜM 1: Great Expectations Validasyonu")
print("=" * 60)
 
context = gx.get_context(mode="ephemeral")
datasource = context.data_sources.add_pandas("pandas_source")
data_asset = datasource.add_dataframe_asset(name="amazon_orders")
batch_definition = data_asset.add_batch_definition_whole_dataframe("batch")
 
suite = context.suites.add(gx.ExpectationSuite(name="amazon_orders_suite"))
suite.add_expectation(gx.expectations.ExpectColumnValuesToNotBeNull(column="order_id"))
suite.add_expectation(gx.expectations.ExpectColumnValuesToBeUnique(column="order_id"))
suite.add_expectation(gx.expectations.ExpectColumnValuesToBeBetween(column="qty", min_value=0))
suite.add_expectation(gx.expectations.ExpectColumnValuesToBeBetween(column="amount", min_value=0))
suite.add_expectation(gx.expectations.ExpectColumnValuesToBeInSet(column="status", value_set=ALLOWED_STATUSES))
 
validation_definition = context.validation_definitions.add(
    gx.ValidationDefinition(name="amazon_validation", data=batch_definition, suite=suite)
)
results = validation_definition.run(batch_parameters={"dataframe": df})
 
ge_passed = 0
ge_failed = 0
ge_failed_details = []
 
for result in results.results:
    expectation_type = result.expectation_config.type
    column = getattr(result.expectation_config, "column", "N/A")
    if result.success:
        ge_passed += 1
        print(f"   ✅ PASS | {expectation_type} | kolon: {column}")
    else:
        ge_failed += 1
        unexpected_count = result.result.get("unexpected_count", "?")
        unexpected_values = result.result.get("partial_unexpected_list", [])
        print(f"   ❌ FAIL | {expectation_type} | kolon: {column}")
        print(f"          Hatalı satır: {unexpected_count} | Örnek: {unexpected_values}")
        ge_failed_details.append({
            "expectation": expectation_type,
            "column": column,
            "unexpected_count": unexpected_count,
            "unexpected_values": unexpected_values,
        })
 
print()
print(f"📊 GE ÖZET: {ge_passed} PASSED | {ge_failed} FAILED")
print()
 
# ============================================================
# BÖLÜM 2 — PYDANTIC VALİDASYONU
# ============================================================
 
print("=" * 60)
print("🔍 BÖLÜM 2: Pydantic Validasyonu")
print("=" * 60)
 
class OrderRow(BaseModel):
    order_id: str
    date: str
    status: str
    qty: int
    amount: float
    currency: str
    ship_country: str
 
    @field_validator("order_id")
    @classmethod
    def order_id_not_empty(cls, v):
        if not v or str(v).strip() == "":
            raise ValueError("order_id boş olamaz")
        return v
 
    @field_validator("qty")
    @classmethod
    def qty_non_negative(cls, v):
        if v < 0:
            raise ValueError(f"qty negatif olamaz: {v}")
        return v
 
    @field_validator("amount")
    @classmethod
    def amount_non_negative(cls, v):
        if v < 0:
            raise ValueError(f"amount negatif olamaz: {v}")
        return v
 
    @field_validator("currency")
    @classmethod
    def currency_must_be_inr(cls, v):
        if v != "INR":
            raise ValueError(f"currency INR olmalı, gelen: {v}")
        return v
 
    @field_validator("ship_country")
    @classmethod
    def country_must_be_in(cls, v):
        if v != "IN":
            raise ValueError(f"ship_country IN olmalı, gelen: {v}")
        return v
 
    @field_validator("status")
    @classmethod
    def status_must_be_valid(cls, v):
        if v not in ALLOWED_STATUSES:
            raise ValueError(f"Geçersiz status: {v}")
        return v
 
    @field_validator("date")
    @classmethod
    def date_format_check(cls, v):
        try:
            datetime.strptime(v, "%m-%d-%y")
        except ValueError:
            raise ValueError(f"Tarih formatı MM-DD-YY olmalı, gelen: {v}")
        return v
 
df_str = pd.read_csv(CSV_PATH, dtype=str).fillna("")
valid_rows = []
invalid_rows = []
 
for index, row in df_str.iterrows():
    try:
        OrderRow(
            order_id     = row["order_id"],
            date         = row["date"],
            status       = row["status"],
            qty          = int(row["qty"]) if row["qty"] != "" else -1,
            amount       = float(row["amount"]) if row["amount"] != "" else -1,
            currency     = row["currency"],
            ship_country = row["ship_country"],
        )
        valid_rows.append(row.to_dict())
        print(f"   ✅ Satır {index+1:02d} GEÇERLİ   | order_id: {row['order_id']}")
    except ValidationError as e:
        errors = [err["msg"] for err in e.errors()]
        row_dict = row.to_dict()
        row_dict["hata_nedeni"] = " | ".join(errors)
        invalid_rows.append(row_dict)
        print(f"   ❌ Satır {index+1:02d} GEÇERSİZ | order_id: {row['order_id'] or 'BOŞ'}")
        for err in errors:
            print(f"          → {err}")
 
pd.DataFrame(valid_rows).to_csv(VALID_OUTPUT, index=False)
pd.DataFrame(invalid_rows).to_csv(INVALID_OUTPUT, index=False)
 
print()
print(f"📊 PYDANTIC ÖZET: {len(valid_rows)} GEÇERLİ | {len(invalid_rows)} GEÇERSİZ")
print(f"   ✅ {VALID_OUTPUT}")
print(f"   ❌ {INVALID_OUTPUT}")
print()
 
# ============================================================
# SLACK BİLDİRİMİ
# ============================================================
 
total_errors = ge_failed + len(invalid_rows)
 
if total_errors == 0:
    send_slack("✅ *Data Quality Pipeline BAŞARILI* — Tüm kontroller geçti.")
else:
    lines = [
        "❌ *Data Quality Pipeline BAŞARISIZ*",
        f"*GE:* {ge_failed} kural başarısız | *Pydantic:* {len(invalid_rows)} geçersiz satır",
    ]
    send_slack("\n".join(lines))
 
# ============================================================
# CI/CD İÇİN KRİTİK: HATA VARSA sys.exit(1)
# Neden: GitHub Actions bir script 0 dışında bir kod ile
# çıkarsa adımı BAŞARISIZ sayar ve pipeline kırmızıya döner.
# Bu sayede hatalı veri push edildiğinde CI otomatik patlar.
# ============================================================
 
if total_errors > 0:
    print("=" * 60)
    print(f"❌ Pipeline BAŞARISIZ: {total_errors} hata bulundu.")
    print("   CI/CD pipeline durduruldu.")
    print("=" * 60)
    sys.exit(1)  # ← bu satır CI'ı kırmızıya çevirir
else:
    print("=" * 60)
    print("✅ Pipeline BAŞARILI: Tüm kontroller geçti.")
    print("=" * 60)
    sys.exit(0)