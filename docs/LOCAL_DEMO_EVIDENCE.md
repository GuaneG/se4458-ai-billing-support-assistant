# Local demonstration evidence

Captured on 2026-11-21 (UTC). Chat, Billing and MCP ran as separate loopback processes. Billing used a synthetic bill in the isolated PostgreSQL test database. This run used the scripted demo model.

## Agent scenarios

### MCP only

**Question**

Ek internet kaç dolar?

**Tool trace**

```json
[
  {
    "name": "search_billing_documentation",
    "arguments": {
      "query": "extra internet cost beyond 20 GB"
    },
    "result": {
      "document_id": "MOB-BILLING-2026-01",
      "passages": [
        {
          "section": "8.1",
          "heading": "What is the cost of extra internet?",
          "excerpt": "Each additional 10 GB block beyond 20 GB costs $10. Partially used blocks are rounded up. See Section 3.2."
        },
        {
          "section": "3.2",
          "heading": "Additional internet blocks",
          "excerpt": "Each additional **10 GB block** costs **$10**. A partially used additional block is charged as a full block. For example, 20 GB costs $50; 21 GB costs $60; 30 GB costs $60; 35 GB costs $70."
        },
        {
          "section": "3.1",
          "heading": "Included internet allowance",
          "excerpt": "Internet access costs **$50 per month** for up to **20 GB**, including months with zero usage."
        }
      ]
    }
  }
]
```

**Final answer**

Rehberin ek internet kuralı [§3.2]

Each additional 10 GB block costs $10. A partially used additional block is charged as a full block. For example, 20 GB costs $50; 21 GB costs $60; 30 GB costs $60; 35 GB costs $70.

### REST only

**Question**

Ekim 2026 faturam ne kadar?

**Tool trace**

```json
[
  {
    "name": "query_bill",
    "arguments": {
      "year": 2026,
      "month": 10
    },
    "result": {
      "total": "80.00",
      "paidAmount": "0.00",
      "remainingBalance": "80.00",
      "status": "unpaid"
    }
  }
]
```

**Final answer**

Ekim 2026 faturan $80.00. Kalan bakiyen $80.00.

### REST + MCP

**Question**

Ekim 2026'da internet ücretim neden $70?

**Tool trace**

```json
[
  {
    "name": "query_bill_details",
    "arguments": {
      "year": 2026,
      "month": 10
    },
    "result": {
      "year": 2026,
      "month": 10,
      "currency": "USD",
      "total": "80.00",
      "paidAmount": "0.00",
      "remainingBalance": "80.00",
      "phoneMinutes": 1350,
      "internetMb": 35000,
      "internetGb": "35.000",
      "chargeBreakdown": [
        {
          "type": "phone",
          "amount": "10.00"
        },
        {
          "type": "internet",
          "amount": "70.00"
        }
      ],
      "page": 1,
      "pageSize": 10,
      "totalItems": 2
    }
  },
  {
    "name": "search_billing_documentation",
    "arguments": {
      "query": "extra internet cost beyond 20 GB"
    },
    "result": {
      "document_id": "MOB-BILLING-2026-01",
      "passages": [
        {
          "section": "8.1",
          "heading": "What is the cost of extra internet?",
          "excerpt": "Each additional 10 GB block beyond 20 GB costs $10. Partially used blocks are rounded up. See Section 3.2."
        },
        {
          "section": "3.2",
          "heading": "Additional internet blocks",
          "excerpt": "Each additional **10 GB block** costs **$10**. A partially used additional block is charged as a full block. For example, 20 GB costs $50; 21 GB costs $60; 30 GB costs $60; 35 GB costs $70."
        },
        {
          "section": "3.1",
          "heading": "Included internet allowance",
          "excerpt": "Internet access costs **$50 per month** for up to **20 GB**, including months with zero usage."
        }
      ]
    }
  }
]
```

**Final answer**

Ekim faturanda 35 GB internet kullanımı ve $70.00 internet ücreti var.

Paketin ilk 20 GB'ı $50. Kalan 15 GB iki adet $10'lık bloğa giriyor. [§3.2]

## Standalone MCP retrieval

- **How much does extra internet cost beyond 20 GB?** → §3.2

  Each additional **10 GB block** costs **$10**. A partially used additional block is charged as a full block. For example, 20 GB costs $50; 21 GB costs $60; 30 GB costs $60; 35 GB costs $70.

- **Can I make a partial payment?** → §5.1

  Subscribers may make full or partial payments. A partial payment reduces the outstanding balance but does **not** mark the bill fully paid.

- **When can my service be restricted after the due date?** → §6.3

  Service **may** be restricted when a bill remains unpaid for **30 days after the due date**, subject to customer support review. This is a policy description, not a live service-status check.

## Simulated payment

The scripted model prepared a $20.00 payment. The bill still had a $80.00 balance before confirmation. After the confirmation request, Billing returned:

```json
{
  "status": "success",
  "paidAmount": "20.00",
  "remainingBalance": "60.00"
}
```

A fresh bill query returned a $60.00 remaining balance. Repeating the same confirmation returned HTTP 409.

## Protected route and tests

The local bill detail route returned HTTP 401 without a JWT and HTTP 200 with the signed owner JWT. The authenticated read used `page=2&pageSize=1` and returned the $70.00 internet charge.

Full local test run with the PostgreSQL read and write test settings:

```text
python -m pytest -q
54 passed in 2.83s
```

[Local demo and test instructions](../README.md)
