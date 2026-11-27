# Bursa Open Transit (BOT)

[ Türkçe ](README.tr.md) · [ English ](README.md)

**Bursa'da toplu ulaşım bilgilerine erişimi kolaylaştırmak için bağımsız ve gönüllü bir girişim.**

Amacımız, otobüs, tramvay ve BursaRay sefer bilgilerinin Google Haritalar üzerinden erişilebilir olmasına, yetkili GTFS Schedule verileri ve daha sonraki aşamada GTFS Realtime aracılığıyla katkı sağlamaktır. Girişim ticari değildir.

## Mevcut durum

**Yalnızca geliştirme aşamasında.** Yazılım temeli hazırdır; GTFS üretimi, gerçek veri bağlayıcıları, barındırma ve gerçek zamanlı entegrasyon henüz uygulanmamıştır. BURULAŞ'ın resmî desteği, yetkili veri erişimi ve platformun yayın onayı beklenmektedir. BOT, BURULAŞ veya Google'ın resmî hizmeti ya da onaylı iş ortağı değildir. Yolculuk planlaması için kullanılabilecek bir veri akışı henüz yoktur.

## İş birliği önerisi

1. Varsa kurumca yetkilendirilmiş mevcut GTFS akışının değerlendirilmesi.
2. Aksi hâlde desteklenen düzenli CSV, JSON veya XML dışa aktarımının dönüştürülmesi.
3. Uygun görülürse belgelenmiş, izinli ve salt okunur API ile entegrasyon.

Pilot kapsamı kurumla birlikte belirlenir. Yayından önce veri doğrulaması ve kurumla örnek yolculuk kontrolleri yapılması öngörülür. Yolcu, kart ve ödeme verileri talep edilmez.

## Geliştirme

Python 3.12 veya üzeri:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest
python -m bursa_transit
```

Komut satırı aracı geliştirme durumunu gösterir ve resmî veri yayınını engeller. Testler gerçek ulaşım verilerinin doğruluğunu kanıtlamaz.

## Belgeler

- [Proje tanımı](docs/PROJECT_CHARTER.md)
- [Mimari](docs/ARCHITECTURE.md)
- [Yol haritası](docs/ROADMAP.md)
- [Veri yönetişimi](docs/DATA_GOVERNANCE.md)
- [İlerleme durumu](docs/PUBLIC_STATUS.md)

Apache-2.0 lisansı proje kodunu kapsar; üçüncü taraf verilerini ve yazışmaları kapsamaz. Katkılar ve genel öneriler GitHub Issues üzerinden iletilebilir. Lütfen özel kayıt, erişim anahtarı veya izinsiz veri paylaşmayın.
