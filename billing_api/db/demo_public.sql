-- The original fictitious October starter bill is the public mobile demo.
UPDATE bills
SET public_summary = TRUE
WHERE subscriber_no = 'A001' AND bill_year = 2026 AND bill_month = 10
    AND phone_minutes = 1350 AND internet_mb = 35000
    AND phone_charge_cents = 1000 AND internet_charge_cents = 7000;
