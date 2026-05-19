import pandas as pd
import great_expectations as gx
import requests
import json
 
# ============================================================
# AYARLAR
# ============================================================
 
CSV_PATH = "data/amazon_orders.csv"
 
# Slack Webhook URL'ini buraya yaz
# https://www.youtube.com/watch?v=UlRq9ouVefE adresinden nasıl alacağını öğrenebilirsin
SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/SENIN/WEBHOOK/URLIN"
 
ALLOWED_STATUSES = ["Shipped", "Delivered", "Cancelled", "Pending", "Returned"]
 
# ============================================================
# ADIM 1 — VERİYİ YÜKLE
# Neden: GE pandas DataFrame üzerinde çalışır.
# ============================================================
 
df = pd.read_csv(CSV_PATH)
print("✅ Veri yüklendi.")
print(f"   Satır sayısı : {len(df)}")
print(f"   Kolonlar     : {list(df.columns)}")
print()
 
# ============================================================
# ADIM 2 — GE CONTEXT OLUŞTUR
# Neden: GE'nin tüm işlemleri bir "context" üzerinden yürür.
# "ephemeral" mod seçiyoruz çünkü diske bir proje yazmak
# istemiyoruz — her çalıştırmada sıfırdan başlar.
# ============================================================
 
context = gx.get_context(mode="ephemeral")
print("✅ GE context oluşturuldu.")
 
# ============================================================
# ADIM 3 — DATASOURCE & DATA ASSET TANIMLA
# Neden: GE veriye doğrudan erişmez, önce bir "datasource"
# tanımlaması gerekir. Pandas datasource, DataFrame'i kaynak
# olarak kabul eder.
# ============================================================
 
datasource = context.data_sources.add_pandas("pandas_source")
data_asset = datasource.add_dataframe_asset(name="amazon_orders")
batch_definition = data_asset.add_batch_definition_whole_dataframe("batch")
batch = batch_definition.get_batch(batch_parameters={"dataframe": df})
print("✅ Datasource ve batch tanımlandı.")
 
# ============================================================
# ADIM 4 — EXPECTATION SUITE OLUŞTUR
# Neden: Suite, tüm kuralların (expectations) toplandığı
# yerdir. Bir tablo için bir suite tanımlarız.
# ============================================================
 
suite = context.suites.add(gx.ExpectationSuite(name="amazon_orders_suite"))
print("✅ Expectation Suite oluşturuldu.")
 
# ============================================================
# ADIM 5 — EXPECTATIONS EKLE
# Her kural bir iş kuralını temsil eder:
# ============================================================
 
# Kural 1: order_id null olmamalı
suite.add_expectation(
    gx.expectations.ExpectColumnValuesToNotBeNull(column="order_id")
)
 
# Kural 2: order_id benzersiz olmalı (duplicate yok)
suite.add_expectation(
    gx.expectations.ExpectColumnValuesToBeUnique(column="order_id")
)
 
# Kural 3: qty sıfır veya pozitif olmalı
suite.add_expectation(
    gx.expectations.ExpectColumnValuesToBeBetween(
        column="qty", min_value=0
    )
)
 
# Kural 4: amount sıfır veya pozitif olmalı
suite.add_expectation(
    gx.expectations.ExpectColumnValuesToBeBetween(
        column="amount", min_value=0
    )
)
 
# Kural 5: status sadece izin verilen değerleri içermeli
suite.add_expectation(
    gx.expectations.ExpectColumnValuesToBeInSet(
        column="status", value_set=ALLOWED_STATUSES
    )
)
 
print("✅ 5 expectation eklendi.")
print()
 
# ============================================================
# ADIM 6 — VALİDASYONU ÇALIŞTIR
# Neden: Validation Result, her expectation'ın geçip
# geçmediğini, kaç satırın hatalı olduğunu gösterir.
# ============================================================
 
validation_definition = context.validation_definitions.add(
    gx.ValidationDefinition(
        name="amazon_validation",
        data=batch_definition,
        suite=suite,
    )
)
 
results = validation_definition.run(batch_parameters={"dataframe": df})
print("✅ Validasyon tamamlandı.")
print()
 
# ============================================================
# ADIM 7 — SONUÇLARI PARSE ET VE YAZDIR
# ============================================================
 
passed = 0
failed = 0
failed_details = []
 
for result in results.results:
    expectation_type = result.expectation_config.type
    column = result.expectation_config.column if hasattr(result.expectation_config, "column") else "N/A"
    success = result.success
 
    if success:
        passed += 1
        print(f"   ✅ PASS | {expectation_type} | kolon: {column}")
    else:
        failed += 1
        unexpected_count = result.result.get("unexpected_count", "?")
        unexpected_values = result.result.get("partial_unexpected_list", [])
        print(f"   ❌ FAIL | {expectation_type} | kolon: {column}")
        print(f"          Hatalı satır sayısı : {unexpected_count}")
        print(f"          Örnek hatalı değerler: {unexpected_values}")
        failed_details.append({
            "expectation": expectation_type,
            "column": column,
            "unexpected_count": unexpected_count,
            "unexpected_values": unexpected_values,
        })
 
print()
print(f"📊 ÖZET: {passed} PASSED | {failed} FAILED")
print()
 
# ============================================================
# ADIM 8 — SLACK BİLDİRİMİ GÖNDER
# Neden: CI/CD pipeline'da veya gece çalışan job'larda
# hata olduğunda ekibi anında haberdar etmek için.
# Sadece hata varsa bildirim gönderiyoruz.
# ============================================================
 
def send_slack_notification(webhook_url, passed, failed, failed_details):
    if failed == 0:
        message = "✅ *Amazon Orders — Veri Kalitesi Kontrolü BAŞARILI*\nTüm expectation'lar geçti."
    else:
        lines = [
            "❌ *Amazon Orders — Veri Kalitesi Kontrolü BAŞARISIZ*",
            f"*Geçen:* {passed}  |  *Başarısız:* {failed}",
            "",
            "*Başarısız Kurallar:*"
        ]
        for d in failed_details:
            lines.append(
                f"• `{d['expectation']}` → kolon: `{d['column']}` "
                f"| hatalı satır: {d['unexpected_count']} "
                f"| örnek değerler: {d['unexpected_values']}"
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
 
 
send_slack_notification(SLACK_WEBHOOK_URL, passed, failed, failed_details)
 