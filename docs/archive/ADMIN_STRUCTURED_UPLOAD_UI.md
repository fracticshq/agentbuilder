# 📊 Admin Dashboard: Structured Knowledge Upload UI

**Purpose**: Guide users to add structured metadata when uploading documents to the knowledge base  
**Goal**: Enable zero-hallucination product cards through proper data structuring  
**User**: Brand admins, agent builders creating knowledge bases

---

## 🎯 Overview

The Admin Dashboard needs an **intelligent document upload interface** that:
1. **Detects content type** (Product, Dealer, FAQ, Office, Guide)
2. **Guides users** to fill structured metadata with examples
3. **Validates data** before uploading to knowledge base
4. **Shows preview** of how data will be stored and used
5. **Provides templates** for common use cases

---

## 🎨 UI/UX Design

### Upload Flow - Step-by-Step

#### **Step 1: Upload Document**

```
┌─────────────────────────────────────────────────────────────┐
│ 📄 Upload Knowledge Base Documents                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │  📁 Drag & Drop Files Here                         │    │
│  │                                                      │    │
│  │  or click to browse                                 │    │
│  │                                                      │    │
│  │  Supported: PDF, DOCX, TXT, MD, HTML               │    │
│  └────────────────────────────────────────────────────┘    │
│                                                              │
│  📂 Selected Files:                                         │
│  • AquaFlow_Faucet_Details.pdf (127 KB)                    │
│  • Mumbai_Dealers_List.xlsx (45 KB)                        │
│                                                              │
│              [Cancel]  [Next: Add Metadata →]              │
└─────────────────────────────────────────────────────────────┘
```

---

#### **Step 2: Select Content Type**

```
┌─────────────────────────────────────────────────────────────┐
│ 🏷️ What type of content are you uploading?                  │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  File: AquaFlow_Faucet_Details.pdf                         │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │   🛍️ Product  │  │  🏪 Dealer   │  │  ❓ FAQ      │     │
│  │              │  │              │  │              │     │
│  │  Product     │  │  Distributor │  │  How-to      │     │
│  │  details,    │  │  contact     │  │  guides,     │     │
│  │  specs,      │  │  info,       │  │  support     │     │
│  │  pricing     │  │  locations   │  │  docs        │     │
│  │              │  │              │  │              │     │
│  │  [Selected]  │  │   [Select]   │  │   [Select]   │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │  🏢 Office    │  │  📋 Category │  │  📖 Guide    │     │
│  │              │  │              │  │              │     │
│  │  Branch      │  │  Product     │  │  General     │     │
│  │  locations,  │  │  categories, │  │  information │     │
│  │  contact     │  │  collections │  │  documents   │     │
│  │              │  │              │  │              │     │
│  │   [Select]   │  │   [Select]   │  │   [Select]   │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│                                                              │
│  💡 Tip: Choosing the right content type enables structured │
│     search and prevents AI hallucinations.                  │
│                                                              │
│              [← Back]  [Next: Add Details →]               │
└─────────────────────────────────────────────────────────────┘
```

---

#### **Step 3A: Product Metadata Form**

```
┌─────────────────────────────────────────────────────────────┐
│ 🛍️ Product Details                                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  File: AquaFlow_Faucet_Details.pdf                         │
│  Content Type: Product                                      │
│                                                              │
│  ┌─ Basic Information ─────────────────────────────────┐   │
│  │                                                       │   │
│  │  SKU (Required) *                                    │   │
│  │  [ESSCO-FAU-001________________]  ℹ️ Unique product  │   │
│  │                                    identifier         │   │
│  │  Product Name (Required) *                           │   │
│  │  [AquaFlow Chrome Kitchen Faucet_____________]       │   │
│  │                                                       │   │
│  │  Category (Required) *                               │   │
│  │  [Faucets ▾]  Subcategory: [Kitchen ▾]             │   │
│  │                                                       │   │
│  │  ✅ Example: Category: "Faucets", Subcategory: "Kitchen" │
│  └───────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌─ Pricing & Availability ──────────────────────────────┐  │
│  │                                                        │  │
│  │  Price (Required) *                                   │  │
│  │  [₹] [3499_____]  ℹ️ Enter in smallest unit (paise)   │  │
│  │                                                        │  │
│  │  Currency                                             │  │
│  │  [INR ▾]                                              │  │
│  │                                                        │  │
│  │  Stock Status                                         │  │
│  │  ☑️ In Stock    Stock Quantity: [47_____]            │  │
│  │                                                        │  │
│  │  ✅ Example: Price: 3499 (₹34.99), Currency: INR      │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌─ Media Assets ────────────────────────────────────────┐  │
│  │                                                        │  │
│  │  Product Image URL (Required) *                       │  │
│  │  [https://cdn.essco.com/images/faucet-001.jpg____]   │  │
│  │                                    [📷 Preview]        │  │
│  │  Additional Images (comma-separated)                  │  │
│  │  [url1, url2, url3_____________________________]      │  │
│  │                                                        │  │
│  │  Product Page URL (Required) *                        │  │
│  │  [https://essco.com/products/aquaflow-chrome____]    │  │
│  │                                    [🔗 Test Link]     │  │
│  │                                                        │  │
│  │  ✅ Example: Use full CDN URLs for images             │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌─ Features & Specifications ───────────────────────────┐  │
│  │                                                        │  │
│  │  Key Features (one per line)                          │  │
│  │  ┌──────────────────────────────────────────────┐    │  │
│  │  │ Single-handle operation                       │    │  │
│  │  │ Ceramic disc cartridge                        │    │  │
│  │  │ 360-degree swivel spout                       │    │  │
│  │  │ Easy installation                             │    │  │
│  │  └──────────────────────────────────────────────┘    │  │
│  │                                                        │  │
│  │  Material: [Chrome-plated brass___________]          │  │
│  │  Finish: [Polished Chrome_________________]          │  │
│  │  Warranty (years): [5____]                           │  │
│  │  Color: [Chrome_______]                              │  │
│  │                                                        │  │
│  │  ✅ Example: List specific, searchable features       │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  [← Back]  [Preview Data]  [Upload to Knowledge Base →]   │
└─────────────────────────────────────────────────────────────┘
```

**Helper Text Examples**:
- SKU: "Unique product identifier (e.g., ESSCO-FAU-001, PROD-SHOWER-042)"
- Price: "Enter in smallest currency unit. For ₹34.99, enter 3499"
- Features: "Specific, searchable attributes customers look for"
- Image URL: "Direct link to product image (must be publicly accessible)"

---

#### **Step 3B: Dealer Metadata Form**

```
┌─────────────────────────────────────────────────────────────┐
│ 🏪 Dealer/Distributor Details                               │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  File: Mumbai_Dealers_List.xlsx                            │
│  Content Type: Dealer                                       │
│                                                              │
│  ┌─ Dealer Information ──────────────────────────────────┐  │
│  │                                                        │  │
│  │  Dealer ID (Required) *                               │  │
│  │  [DEALER-MUM-001____________]  ℹ️ Internal ID          │  │
│  │                                                        │  │
│  │  Dealer Name (Required) *                             │  │
│  │  [ABC Hardware & Sanitaryware_____________]           │  │
│  │                                                        │  │
│  │  City (Required) *                                    │  │
│  │  [Mumbai ▾]  State: [Maharashtra ▾]                  │  │
│  │                                                        │  │
│  │  ✅ Example: Dealer ID: "DEALER-MUM-001"               │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌─ Contact Information ─────────────────────────────────┐  │
│  │                                                        │  │
│  │  Phone (Required) *                                   │  │
│  │  [+91] [9876543210____________]                       │  │
│  │                                                        │  │
│  │  Email                                                │  │
│  │  [contact@abchardware.com_______________]             │  │
│  │                                                        │  │
│  │  Address                                              │  │
│  │  ┌──────────────────────────────────────────────┐    │  │
│  │  │ 123 Main Street, Andheri West                 │    │  │
│  │  │ Mumbai, Maharashtra - 400053                  │    │  │
│  │  └──────────────────────────────────────────────┘    │  │
│  │                                                        │  │
│  │  Website                                              │  │
│  │  [https://abchardware.com_______________]             │  │
│  │                                                        │  │
│  │  ✅ Example: Use standard phone format with country code│
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌─ Additional Details ──────────────────────────────────┐  │
│  │                                                        │  │
│  │  Authorized Products (optional)                       │  │
│  │  [Faucets, Showers, Toilets_____________]            │  │
│  │                                                        │  │
│  │  Service Areas (optional)                             │  │
│  │  [Mumbai, Navi Mumbai, Thane____________]            │  │
│  │                                                        │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  [← Back]  [Preview Data]  [Upload to Knowledge Base →]   │
└─────────────────────────────────────────────────────────────┘
```

---

#### **Step 4: Data Preview & Validation**

```
┌─────────────────────────────────────────────────────────────┐
│ 👁️ Preview: How Your Data Will Be Stored                    │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  File: AquaFlow_Faucet_Details.pdf                         │
│                                                              │
│  ┌─ Document Structure ──────────────────────────────────┐  │
│  │                                                        │  │
│  │  📄 Content (from PDF)                                │  │
│  │  "The AquaFlow Chrome Faucet is a premium kitchen..." │  │
│  │  [Show Full Content ▾]                                │  │
│  │                                                        │  │
│  │  🏷️ Content Type: product                             │  │
│  │                                                        │  │
│  │  📊 Structured Product Data:                          │  │
│  │  {                                                    │  │
│  │    "sku": "ESSCO-FAU-001",                            │  │
│  │    "name": "AquaFlow Chrome Kitchen Faucet",          │  │
│  │    "price": 3499,                                     │  │
│  │    "currency": "INR",                                 │  │
│  │    "category": "faucets",                             │  │
│  │    "subcategory": "kitchen",                          │  │
│  │    "image_url": "https://cdn.essco.com/...",          │  │
│  │    "product_url": "https://essco.com/products/...",   │  │
│  │    "in_stock": true,                                  │  │
│  │    "stock_quantity": 47,                              │  │
│  │    "features": [                                      │  │
│  │      "Single-handle operation",                       │  │
│  │      "Ceramic disc cartridge",                        │  │
│  │      "360-degree swivel spout"                        │  │
│  │    ],                                                 │  │
│  │    "specifications": {                                │  │
│  │      "material": "Chrome-plated brass",               │  │
│  │      "warranty_years": 5,                             │  │
│  │      "color": "Chrome"                                │  │
│  │    }                                                  │  │
│  │  }                                                    │  │
│  │                                                        │  │
│  │  [Copy JSON]  [Edit Metadata]                        │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ✅ Validation Results:                                     │
│  • ✅ SKU is unique                                         │
│  • ✅ All required fields present                           │
│  • ✅ Image URL accessible (tested)                         │
│  • ✅ Product URL valid (tested)                            │
│  • ✅ Price is valid number                                 │
│                                                              │
│  💡 How This Enables Zero-Hallucination:                    │
│  When a user asks "show me faucets under 5000", the AI will:│
│  1. Search for content_type="product" + price <= 5000       │
│  2. Inject THIS EXACT DATA into the AI prompt               │
│  3. AI cannot invent SKU, price, or URL - only format it    │
│  4. Result: Accurate product cards, zero hallucinations! 🎯 │
│                                                              │
│  [← Edit]  [Upload Another]  [Finish & Upload All →]      │
└─────────────────────────────────────────────────────────────┘
```

---

## 📋 Template Library

### Pre-built Templates (Accessible from Upload UI)

#### **Template 1: Product Document**
```yaml
# Product Template
content_type: product

product_data:
  sku: "ESSCO-PROD-XXX"          # Required
  name: "Product Name"            # Required
  price: 0                        # Required (in paise/cents)
  currency: "INR"                 # Required
  category: "category"            # Required
  subcategory: "subcategory"
  
  image_url: "https://..."        # Required
  images: ["url1", "url2"]
  product_url: "https://..."      # Required
  
  in_stock: true
  stock_quantity: 0
  
  features:
    - "Feature 1"
    - "Feature 2"
  
  specifications:
    material: "Material"
    warranty_years: 0
    color: "Color"

# Example filled:
# sku: "ESSCO-FAU-001"
# name: "AquaFlow Chrome Kitchen Faucet"
# price: 3499 (₹34.99)
```

#### **Template 2: Dealer Document**
```yaml
# Dealer Template
content_type: dealer

dealer_data:
  dealer_id: "DEALER-XXX-YYY"     # Required
  name: "Dealer Name"              # Required
  city: "City"                     # Required
  state: "State"
  
  phone: "+91-XXXXXXXXXX"          # Required
  email: "email@example.com"
  address: "Full address"
  website: "https://..."
  
  authorized_products:
    - "Product Category 1"
    - "Product Category 2"
  
  service_areas:
    - "Area 1"
    - "Area 2"

# Example filled:
# dealer_id: "DEALER-MUM-001"
# name: "ABC Hardware & Sanitaryware"
# city: "Mumbai"
```

#### **Template 3: FAQ Document**
```yaml
# FAQ Template
content_type: faq

# No structured data needed
# Just upload your FAQ document

# The content will be searchable, but won't
# appear as structured cards
```

---

## 🎨 Visual Examples & Tooltips

### Interactive Examples in UI

```
┌─────────────────────────────────────────────────────────────┐
│ 💡 Need help? See examples                                  │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  [View Example: Bathroom Faucet Product]                    │
│  [View Example: Dealer in Delhi]                            │
│  [View Example: Installation FAQ]                           │
│                                                              │
│  ┌─ Example: Bathroom Faucet Product ─────────────────┐    │
│  │                                                      │    │
│  │  SKU: "ESSCO-FAU-BATH-042"                          │    │
│  │  Name: "Cascade Waterfall Bathroom Faucet"          │    │
│  │  Price: 5999 (displays as ₹59.99)                  │    │
│  │  Category: Faucets → Bathroom                       │    │
│  │  Image: https://cdn.essco.com/images/cascade.jpg    │    │
│  │  Product URL: https://essco.com/products/cascade    │    │
│  │  In Stock: Yes                                      │    │
│  │  Features:                                          │    │
│  │    - Waterfall spout design                         │    │
│  │    - Solid brass construction                       │    │
│  │    - Chrome finish                                  │    │
│  │    - Wall-mounted                                   │    │
│  │                                                      │    │
│  │  [Use This Example]  [Start Fresh]                  │    │
│  └──────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔧 Implementation Components

### Frontend Components (React/TypeScript)

#### **1. DocumentUploadWizard.tsx**
```typescript
interface DocumentUploadWizardProps {
  agentId: string;
  brandId: string;
  onComplete: () => void;
}

type ContentType = 'product' | 'dealer' | 'faq' | 'office' | 'category' | 'guide';

const DocumentUploadWizard: React.FC<DocumentUploadWizardProps> = ({
  agentId,
  brandId,
  onComplete
}) => {
  const [step, setStep] = useState<'upload' | 'select' | 'metadata' | 'preview'>();
  const [files, setFiles] = useState<File[]>([]);
  const [contentType, setContentType] = useState<ContentType>();
  const [structuredData, setStructuredData] = useState<any>();
  
  return (
    <div className="upload-wizard">
      {step === 'upload' && <FileUploadStep />}
      {step === 'select' && <ContentTypeSelector />}
      {step === 'metadata' && <MetadataForm contentType={contentType} />}
      {step === 'preview' && <DataPreview />}
    </div>
  );
};
```

#### **2. ProductMetadataForm.tsx**
```typescript
interface ProductMetadataFormProps {
  onSubmit: (data: ProductData) => void;
  initialData?: ProductData;
}

interface ProductData {
  sku: string;
  name: string;
  price: number;
  currency: string;
  category: string;
  subcategory?: string;
  image_url: string;
  images?: string[];
  product_url: string;
  in_stock: boolean;
  stock_quantity?: number;
  features: string[];
  specifications: Record<string, any>;
}

const ProductMetadataForm: React.FC<ProductMetadataFormProps> = ({
  onSubmit,
  initialData
}) => {
  const { register, handleSubmit, formState: { errors } } = useForm<ProductData>();
  
  return (
    <form onSubmit={handleSubmit(onSubmit)}>
      <FormSection title="Basic Information">
        <Input
          label="SKU"
          {...register('sku', { required: 'SKU is required' })}
          placeholder="ESSCO-FAU-001"
          tooltip="Unique product identifier"
          error={errors.sku?.message}
        />
        <Input
          label="Product Name"
          {...register('name', { required: 'Name is required' })}
          placeholder="AquaFlow Chrome Kitchen Faucet"
          error={errors.name?.message}
        />
        <Select
          label="Category"
          {...register('category', { required: 'Category is required' })}
          options={['Faucets', 'Showers', 'Toilets', 'Basins']}
          error={errors.category?.message}
        />
      </FormSection>
      
      <FormSection title="Pricing & Availability">
        <PriceInput
          label="Price"
          {...register('price', { 
            required: 'Price is required',
            min: { value: 0, message: 'Price must be positive' }
          })}
          currency="INR"
          helpText="Enter in smallest unit (paise). Example: 3499 for ₹34.99"
          error={errors.price?.message}
        />
        <Checkbox
          label="In Stock"
          {...register('in_stock')}
        />
      </FormSection>
      
      {/* More sections... */}
      
      <ExampleBanner>
        <strong>Example:</strong> SKU: "ESSCO-FAU-001", Price: 3499 (₹34.99)
      </ExampleBanner>
      
      <ButtonGroup>
        <Button variant="secondary">Preview Data</Button>
        <Button type="submit" variant="primary">Upload to Knowledge Base</Button>
      </ButtonGroup>
    </form>
  );
};
```

#### **3. TemplateLibrary.tsx**
```typescript
const TEMPLATES = {
  product: {
    name: 'Product Document',
    description: 'For products with SKU, pricing, and images',
    example: {
      sku: 'ESSCO-FAU-001',
      name: 'AquaFlow Chrome Kitchen Faucet',
      price: 3499,
      category: 'faucets',
      // ... full example
    }
  },
  dealer: {
    name: 'Dealer/Distributor',
    description: 'For dealer contact information',
    example: {
      dealer_id: 'DEALER-MUM-001',
      name: 'ABC Hardware',
      city: 'Mumbai',
      // ... full example
    }
  }
};

const TemplateLibrary: React.FC<{onSelect: (template: any) => void}> = ({
  onSelect
}) => {
  return (
    <div className="template-library">
      <h3>Choose a Template</h3>
      {Object.entries(TEMPLATES).map(([key, template]) => (
        <TemplateCard
          key={key}
          title={template.name}
          description={template.description}
          example={template.example}
          onUse={() => onSelect(template.example)}
        />
      ))}
    </div>
  );
};
```

---

## 🧪 Validation Rules

### Client-Side Validation

```typescript
const productValidationRules = {
  sku: {
    required: true,
    pattern: /^[A-Z0-9-]+$/,
    message: 'SKU must contain only uppercase letters, numbers, and hyphens'
  },
  name: {
    required: true,
    minLength: 3,
    maxLength: 200
  },
  price: {
    required: true,
    type: 'number',
    min: 0,
    message: 'Price must be a positive number in smallest currency unit'
  },
  image_url: {
    required: true,
    pattern: /^https?:\/\/.+\.(jpg|jpeg|png|webp)$/i,
    async: true,  // Test if URL is accessible
    message: 'Must be a valid, accessible image URL'
  },
  product_url: {
    required: true,
    pattern: /^https?:\/\/.+$/,
    message: 'Must be a valid URL'
  }
};

// Async validation
async function validateImageUrl(url: string): Promise<boolean> {
  try {
    const response = await fetch(url, { method: 'HEAD' });
    return response.ok && response.headers.get('content-type')?.startsWith('image/');
  } catch {
    return false;
  }
}
```

### Server-Side Validation

```python
# apps/api/app/schemas/knowledge_base.py

from pydantic import BaseModel, Field, validator, HttpUrl
from typing import Optional, List, Dict, Literal

class ProductData(BaseModel):
    """Structured product data schema."""
    sku: str = Field(..., regex=r'^[A-Z0-9-]+$')
    name: str = Field(..., min_length=3, max_length=200)
    price: int = Field(..., ge=0)
    currency: str = Field(default="INR")
    category: str
    subcategory: Optional[str] = None
    
    image_url: HttpUrl
    images: Optional[List[HttpUrl]] = []
    product_url: HttpUrl
    
    in_stock: bool = True
    stock_quantity: Optional[int] = Field(None, ge=0)
    
    features: List[str] = []
    specifications: Dict[str, any] = {}
    
    @validator('sku')
    def validate_sku_unique(cls, v):
        # Check uniqueness against database
        # (implemented in service layer)
        return v.upper()
    
    @validator('price')
    def validate_price_reasonable(cls, v):
        if v > 10000000:  # 100,000 INR in paise
            raise ValueError('Price seems unreasonably high. Please verify.')
        return v

class KnowledgeBaseDocument(BaseModel):
    """Enhanced knowledge base document with structured data."""
    doc_id: str
    content: str
    content_type: Literal['product', 'dealer', 'faq', 'office', 'category', 'guide']
    
    product_data: Optional[ProductData] = None
    dealer_data: Optional[DealerData] = None
    office_data: Optional[OfficeData] = None
    
    @validator('product_data')
    def validate_product_data_required(cls, v, values):
        if values.get('content_type') == 'product' and not v:
            raise ValueError('product_data is required for content_type=product')
        return v
```

---

## 📊 Success Metrics for Admin UI

| Metric | Target | How to Measure |
|--------|--------|----------------|
| **Upload Completion Rate** | >90% | % of users who complete upload wizard |
| **Metadata Accuracy** | >95% | % of uploads with valid structured data |
| **Template Usage** | >60% | % of uploads using templates |
| **Validation Errors** | <5% | % of uploads failing validation |
| **Time to Upload** | <3 min | Average time from file select to complete |

---

## 🎯 Next Steps for Implementation

### Week 1: Admin UI Development
1. **Day 1-2**: Build DocumentUploadWizard component
2. **Day 3-4**: Build content type selector and metadata forms
3. **Day 5**: Build template library
4. **Day 6-7**: Add validation and preview functionality

### Week 2: Backend Integration
1. Extend ingestion API to accept structured metadata
2. Add server-side validation schemas
3. Create database migration for new fields
4. Build admin API endpoints for template management

### Week 3: Testing & Refinement
1. User testing with sample uploads
2. Iterate on UX based on feedback
3. Add more templates and examples
4. Performance optimization

---

## 📚 Documentation for Users

### In-App Help Text

```markdown
# What is Structured Metadata?

When you upload documents to your agent's knowledge base, adding
structured metadata helps the AI provide accurate, factual responses.

## Why It Matters

Without structured data:
❌ AI might invent product prices
❌ AI might create fake SKU numbers
❌ AI might guess product availability

With structured data:
✅ AI uses EXACT prices from your data
✅ AI shows REAL SKU numbers
✅ AI displays ACCURATE availability

## How It Works

1. Choose your content type (Product, Dealer, FAQ, etc.)
2. Fill in the structured fields (SKU, price, images, etc.)
3. Upload your document
4. AI will NEVER hallucinate these facts!

## Need Help?

• Check out our example templates
• Watch the tutorial video
• Contact support@essco.com
```

---

**Status**: 📋 Ready for Implementation  
**Priority**: 🔴 Critical (blocks zero-hallucination feature)  
**Timeline**: 2-3 weeks for full admin UI
