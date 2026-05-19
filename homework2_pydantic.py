import pandas as pd
import requests
import json
from pydantic import BaseModel, field_validator, ValidationError
from datetime import datetime
from typing import List
 
# ============================================================
# AYARLAR
# ============================================================
 
CSV_PATH = "data/amazon_orders.csv"
VALID_OUTPUT   = "data/valid_rows.csv"
INVALID_OUTPUT = "data/invalid_rows.csv"
 
SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/SENIN/WEBHOOK/URLIN"
 
# ============================================================
# ADIM 1 — PYDANTIC MODELİ TANIMLA
# Neden: GE tüm dataframe'e bakıyordu (tablo seviyesi).
# Pydantic ise her satırı ayrı ayrı bir Python nesnesi
# olarak doğrular (satır seviyesi). Bu sayede hangi satırda
# tam olarak ne hatalı olduğunu biliriz.
# ============================================================
 
class OrderRow(BaseModel):
    order_id: str
    date: str
    status: str
    qty: int
    amount: float
    currency: str
    ship_country: str
 
    # Kural 1: order_id boş olamaz
    @field_validator("order_id")
    @classmethod
    def order_id_not_empty(cls, v):
        if not v or str(v).strip() == "":
            raise ValueError("order_id boş olamaz")
        return v
 
    # Kural 2: qty sıfır veya pozitif olmalı
    @field_validator("qty")
    @classmethod
    def qty_non_negative(cls, v):
        if v < 0:
            raise ValueError(f"qty negatif olamaz: {v}")
        return v
 
    # Kural 3: amount sıfır veya pozitif olmalı
    @field_validator("amount")
    @classmethod
    def amount_non_negative(cls, v):
        if v < 0:
            raise ValueError(f"amount negatif olamaz: {v}")
        return v
 
    # Kural 4: currency sadece INR olmalı
    @field_validator("currency")
    @classmethod
    def currency_must_be_inr(cls, v):
        if v != "INR":
            raise ValueError(f"currency INR olmalı, gelen: {v}")
        return v
 
    # Kural 5: ship_country sadece IN olmalı
    @field_validator("ship_country")
    @classmethod
    def country_must_be_in(cls, v):
        if v != "IN":
            raise ValueError(f"ship_country IN olmalı, gelen: {v}")
        return v
 
    # Kural 6: status izin verilen değerlerde olmalı
    @field_validator("status")
    @classmethod
    def status_must_be_valid(cls, v):
        allowed = ["Shipped", "Delivered", "Cancelled", "Pending", "Returned"]
        if v not in allowed:
            raise ValueError(f"Geçersiz status: {v}. İzin verilenler: {allowed}")
        return v
 
    # Kural 7: tarih formatı MM-DD-YY olmalı
    @field_validator("date")
    @classmethod
    def date_format_check(cls, v):
        try:
            datetime.strptime(v, "%m-%d-%y")
        except ValueError:
            raise ValueError(f"Tarih formatı MM-DD-YY olmalı, gelen: {v}")
        return v
 
 
# ============================================================
# ADIM 2 — VERİYİ YÜKLE
# ============================================================
 
df = pd.read_csv(CSV_PATH, dtype=str)  # dtype=str: tüm kolonları string oku
                                        # böylece NaN'ları da görebiliriz
df = df.fillna("")  # NaN değerleri boş string'e çevir
 
print("✅ Veri yüklendi.")
print(f"   Toplam satır: {len(df)}")
print()
 
# ============================================================
# ADIM 3 — HER SATIRI DOĞRULA
# Neden: Pydantic her satır için ayrı bir nesne oluşturur.
# Eğer satır kurallara uymuyorsa ValidationError fırlatır,
# biz de o satırı "invalid" listesine alırız.
# ============================================================
 
valid_rows   = []
invalid_rows = []
 
for index, row in df.iterrows():
    try:
        # Satırı Pydantic modeline ver — tüm kurallar otomatik kontrol edilir
        order = OrderRow(
            order_id    = row["order_id"],
            date        = row["date"],
            status      = row["status"],
            qty         = int(row["qty"]) if row["qty"] != "" else -1,
            amount      = float(row["amount"]) if row["amount"] != "" else -1,
            currency    = row["currency"],
            ship_country= row["ship_country"],
        )
        valid_rows.append(row.to_dict())
        print(f"   ✅ Satır {index+1:02d} GEÇERLİ   | order_id: {row['order_id']}")
 
    except ValidationError as e:
        # Hangi kuralların ihlal edildiğini topla
        errors = [err["msg"] for err in e.errors()]
        row_dict = row.to_dict()
        row_dict["hata_nedeni"] = " | ".join(errors)
        invalid_rows.append(row_dict)
        print(f"   ❌ Satır {index+1:02d} GEÇERSİZ | order_id: {row['order_id'] or 'BOŞ'}")
        for err in errors:
            print(f"          → {err}")
 
# ============================================================
# ADIM 4 — SONUÇLARI CSV OLARAK KAYDET
# Neden: Geçersiz satırları ayrı bir dosyaya atmak,
# veri mühendisinin hangi kayıtları düzeltmesi gerektiğini
# kolayca görmesini sağlar.
# ============================================================
 
valid_df   = pd.DataFrame(valid_rows)
invalid_df = pd.DataFrame(invalid_rows)
 
valid_df.to_csv(VALID_OUTPUT, index=False)
invalid_df.to_csv(INVALID_OUTPUT, index=False)
 
print()
print(f"📊 ÖZET: {len(valid_rows)} GEÇERLİ | {len(invalid_rows)} GEÇERSİZ")
print(f"   ✅ Geçerli satırlar  → {VALID_OUTPUT}")
print(f"   ❌ Geçersiz satırlar → {INVALID_OUTPUT}")
print()
 
# ============================================================
# ADIM 5 — SLACK BİLDİRİMİ
# ============================================================
 
def send_slack_notification(webhook_url, valid_count, invalid_count, invalid_rows):
    if invalid_count == 0:
        message = "✅ *Amazon Orders — Pydantic Validasyon BAŞARILI*\nTüm satırlar geçerli."
    else:
        lines = [
            "❌ *Amazon Orders — Pydantic Validasyon BAŞARISIZ*",
            f"*Geçerli:* {valid_count}  |  *Geçersiz:* {invalid_count}",
            "",
            "*Geçersiz Satırlar:*"
        ]
        for row in invalid_rows:
            lines.append(
                f"• `{row.get('order_id') or 'BOŞ'}` → {row.get('hata_nedeni')}"
            )
        message = "\n".join(lines)
 
    payload = {"text": message}
    try:
        response = requests.post(
            webhook_url,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if response.status_code == 200:
            print("✅ Slack bildirimi gönderildi.")
        else:
            print(f"⚠️  Slack bildirimi gönderilemedi. Status: {response.status_code}")
    except Exception as e:
        print(f"⚠️  Slack bağlantı hatası: {e}")
 
 
send_slack_notification(SLACK_WEBHOOK_URL, len(valid_rows), len(invalid_rows), invalid_rows)