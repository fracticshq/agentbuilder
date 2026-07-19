import React, { useState, useEffect } from 'react';
import { ArrowRightIcon, CheckCircleIcon, ExclamationTriangleIcon } from '@heroicons/react/24/outline';

const isDev = import.meta.env.DEV;

interface JsonFieldMapperProps {
  jsonData: any[];
  contentType: 'product' | 'dealer';
  onMappingComplete: (mappedData: any[]) => void;
  onBack: () => void;
}

interface FieldMappingConfig {
  mode: 'json' | 'fixed' | 'empty'; // json = map from JSON field, fixed = hardcoded value, empty = skip
  value: string; // JSON field name OR fixed value
}

interface FieldMapping {
  [requiredField: string]: FieldMappingConfig;
}

interface DetectedField {
  name: string;
  type: string;
  sampleValue: any;
  count: number;
}

export default function JsonFieldMapper({ 
  jsonData, 
  contentType, 
  onMappingComplete,
  onBack 
}: JsonFieldMapperProps) {
  const [detectedFields, setDetectedFields] = useState<DetectedField[]>([]);
  const [mapping, setMapping] = useState<FieldMapping>({});
  const [previewData, setPreviewData] = useState<any[]>([]);
  const [errors, setErrors] = useState<string[]>([]);

  // Required fields for each content type
  const requiredFields = contentType === 'product'
    ? {
        sku: { type: 'string', description: 'Product SKU/ID (unique identifier)' },
        name: { type: 'string', description: 'Product name/title' },
        price: { type: 'number', description: 'Product price (number, in smallest currency unit)' },
        currency: { type: 'string', description: 'Currency code (e.g., INR, USD)' },
        category: { type: 'string', description: 'Product category' },
      }
    : {
        dealer_id: { type: 'string', description: 'Dealer ID (unique identifier)' },
        name: { type: 'string', description: 'Dealer/Store name' },
        city: { type: 'string', description: 'City location' },
        phone: { type: 'string', description: 'Contact phone number' },
      };

  const optionalFields = contentType === 'product'
    ? {
        image_url: { type: 'string', description: 'Product image URL' },
        product_url: { type: 'string', description: 'Product page URL' },
        in_stock: { type: 'boolean', description: 'Stock availability (true/false)' },
        features: { type: 'array', description: 'Array of feature strings' },
      }
    : {
        state: { type: 'string', description: 'State/Province' },
        email: { type: 'string', description: 'Contact email' },
        address: { type: 'string', description: 'Full address' },
      };

  // Auto-detect fields from JSON data
  useEffect(() => {
    if (!jsonData || jsonData.length === 0) return;

    const fieldStats: { [key: string]: DetectedField } = {};

    jsonData.forEach(item => {
      Object.keys(item).forEach(key => {
        if (!fieldStats[key]) {
          fieldStats[key] = {
            name: key,
            type: Array.isArray(item[key]) ? 'array' : typeof item[key],
            sampleValue: item[key],
            count: 0,
          };
        }
        if (item[key] !== null && item[key] !== undefined) {
          fieldStats[key].count++;
        }
      });
    });

    const fields = Object.values(fieldStats).sort((a, b) => b.count - a.count);
    setDetectedFields(fields);

    // Auto-map fields with exact or similar names
    const autoMapping: FieldMapping = {};
    
    Object.keys(requiredFields).forEach(requiredField => {
      // Try exact match first
      const exactMatch = fields.find(f => f.name.toLowerCase() === requiredField.toLowerCase());
      if (exactMatch) {
        autoMapping[requiredField] = { mode: 'json', value: exactMatch.name };
        return;
      }

      // Try common aliases
      const aliases: { [key: string]: string[] } = {
        sku: ['product_id', 'productId', 'id', 'code', 'item_id', 'itemId', 'item_code', 'itemCode'],
        name: ['title', 'product_name', 'productName', 'product_title', 'productTitle', 'description', 'item_name'],
        price: ['amount', 'cost', 'product_price', 'productPrice', 'retail_price', 'retailPrice', 'retail_price_cents'],
        currency: ['curr', 'currency_code', 'currencyCode', 'price_currency', 'priceCurrency'],
        category: ['cat', 'product_category', 'productCategory', 'product_type', 'productType', 'item_category', 'type'],
        image_url: ['image', 'img', 'imageUrl', 'product_image', 'productImage', 'thumbnail'],
        product_url: ['url', 'link', 'productUrl', 'product_link'],
        in_stock: ['stock', 'inStock', 'stock_available', 'available', 'availability'],
        features: ['tags', 'attributes', 'specs', 'specifications'],
        dealer_id: ['id', 'dealerId', 'dealer_code', 'dealerCode', 'code'],
        city: ['location', 'town'],
        state: ['province', 'region'],
        phone: ['tel', 'telephone', 'mobile', 'contact', 'phone_number', 'phoneNumber'],
        email: ['mail', 'e-mail', 'contact_email'],
      };

      const fieldAliases = aliases[requiredField] || [];
      const aliasMatch = fields.find(f => 
        fieldAliases.some(alias => f.name.toLowerCase() === alias.toLowerCase())
      );

      if (aliasMatch) {
        autoMapping[requiredField] = { mode: 'json', value: aliasMatch.name };
      }
    });

    setMapping(autoMapping);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jsonData]);

  // Helper function to parse fixed values to correct types
  const parseFixedValue = (field: string, value: string): any => {
    const allFields = { ...requiredFields, ...optionalFields };
    const fieldType = (allFields as any)[field]?.type;

    try {
      if (fieldType === 'number') {
        const num = parseFloat(value);
        return isNaN(num) ? 0 : num;
      } else if (fieldType === 'boolean') {
        const lowerValue = value.toLowerCase().trim();
        if (lowerValue === 'true' || lowerValue === '1' || lowerValue === 'yes') {
          return true;
        } else if (lowerValue === 'false' || lowerValue === '0' || lowerValue === 'no') {
          return false;
        }
        return Boolean(value);
      } else if (fieldType === 'array') {
        // Try to parse JSON array
        if (value.trim().startsWith('[')) {
          return JSON.parse(value);
        } else if (value.includes(',')) {
          return value.split(',').map(v => v.trim());
        } else if (value.trim() === '') {
          return [];
        } else {
          return [value];
        }
      }
      return value; // For 'string' type
    } catch (error) {
      console.error('Unable to parse configured JSON field value', { field, error });
      return value;
    }
  };

  // Update preview when mapping changes
  useEffect(() => {
    if (!jsonData || Object.keys(mapping).length === 0) return;

    try {
      const mapped = jsonData.map(item => {
        const newItem: any = {};

        // Map required fields
        Object.keys(requiredFields).forEach(reqField => {
          const mappingConfig = mapping[reqField];
          if (!mappingConfig) return;

          if (mappingConfig.mode === 'json') {
            // Map from JSON field
            if (mappingConfig.value in item) {
              newItem[reqField] = item[mappingConfig.value];
            }
          } else if (mappingConfig.mode === 'fixed') {
            // Use fixed value for all items (with type parsing)
            newItem[reqField] = parseFixedValue(reqField, mappingConfig.value);
          }
          // mode === 'empty' → skip this field
        });

        // Map optional fields
        Object.keys(optionalFields).forEach(optField => {
          const mappingConfig = mapping[optField];
          if (!mappingConfig) return;

          if (mappingConfig.mode === 'json') {
            if (mappingConfig.value in item) {
              newItem[optField] = item[mappingConfig.value];
            }
          } else if (mappingConfig.mode === 'fixed') {
            newItem[optField] = parseFixedValue(optField, mappingConfig.value);
          }
        });

        return newItem;
      });

      setPreviewData(mapped.slice(0, 3));
      validateMapping(mapped);
    } catch (error) {
      setErrors([`Mapping error: ${error instanceof Error ? error.message : 'Unknown error'}`]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapping, jsonData]);

  const validateMapping = (mappedData: any[]) => {
    const newErrors: string[] = [];

    // Check all required fields are mapped
    Object.keys(requiredFields).forEach(field => {
      const config = mapping[field];
      if (!config || config.mode === 'empty') {
        newErrors.push(`Required field "${field}" is not mapped`);
      } else if (config.mode === 'fixed' && (!config.value || config.value.trim() === '')) {
        newErrors.push(`Required field "${field}" has empty fixed value`);
      }
    });

    // Validate first few items
    mappedData.slice(0, 10).forEach((item, idx) => {
      Object.keys(requiredFields).forEach(field => {
        if (!item[field] || item[field] === null || item[field] === '') {
          newErrors.push(`Item ${idx + 1}: Missing value for required field "${field}"`);
        }
      });

      // Type validation
      if (contentType === 'product' && item.price !== undefined) {
        if (typeof item.price !== 'number') {
          newErrors.push(`Item ${idx + 1}: Price must be a number (got ${typeof item.price})`);
        }
      }
    });

    setErrors(newErrors);
  };

  const handleFieldMapping = (requiredField: string, mode: 'json' | 'fixed' | 'empty', value: string) => {
    setMapping(prev => ({
      ...prev,
      [requiredField]: { mode, value },
    }));
  };

  const handleConfirm = () => {
    if (errors.length > 0) return;

    isDev && console.log('[JsonFieldMapper] handleConfirm - Starting mapping with config:', mapping);

    const mappedData = jsonData.map((item, idx) => {
      const newItem: any = {};
      
      // Map all fields (required + optional)
      [...Object.keys(requiredFields), ...Object.keys(optionalFields)].forEach(field => {
        const config = mapping[field];
        if (!config || config.mode === 'empty') return;

        if (config.mode === 'json') {
          if (config.value in item) {
            newItem[field] = item[config.value];
          }
        } else if (config.mode === 'fixed') {
          // Parse fixed values to correct types using helper
          const parsedValue = parseFixedValue(field, config.value);
          newItem[field] = parsedValue;

          if (idx === 0) {
            isDev && console.log('[JsonFieldMapper] Parsed fixed field', {
              field,
              valueType: typeof parsedValue,
            });
          }
        }
      });

      if (idx === 0) {
        isDev && console.log('[JsonFieldMapper] First mapped item:', newItem);
      }

      return newItem;
    });

    isDev && console.log('[JsonFieldMapper] Total mapped items:', mappedData.length);
    isDev && console.log('[JsonFieldMapper] Sample mapped data:', mappedData.slice(0, 2));

    onMappingComplete(mappedData);
  };

  const getFieldColor = (field: string) => {
    const config = mapping[field];
    if (!config || config.mode === 'empty') {
      return 'border-gray-300 bg-white';
    }
    return errors.some(e => e.includes(`"${field}"`)) ? 'border-red-300 bg-red-50' : 'border-green-300 bg-green-50';
  };

  const renderFieldMapping = (fieldName: string, fieldInfo: any, isRequired: boolean) => {
    const config = mapping[fieldName] || { mode: 'empty', value: '' };

    return (
      <div key={fieldName} className={`border rounded-lg p-4 ${getFieldColor(fieldName)}`}>
        <div className="grid grid-cols-12 gap-4 items-start">
          {/* Required Field */}
          <div className="col-span-5">
            <label className="block text-sm font-medium text-gray-900 mb-1">
              {fieldName} {isRequired && <span className="text-red-500">*</span>}
            </label>
            <p className="text-xs text-gray-600">{fieldInfo.description}</p>
            <p className="text-xs text-gray-500 mt-1">Type: {fieldInfo.type}</p>
          </div>

          {/* Arrow */}
          <div className="col-span-1 flex justify-center pt-2">
            <ArrowRightIcon className="h-5 w-5 text-gray-400" />
          </div>

          {/* Mapping Controls */}
          <div className="col-span-6 space-y-2">
            {/* Mode selector */}
            <div className="flex gap-2">
              <button
                onClick={() => handleFieldMapping(fieldName, 'json', config.mode === 'json' ? config.value : '')}
                className={`px-3 py-1 text-xs rounded ${
                  config.mode === 'json' 
                    ? 'bg-primary-600 text-white' 
                    : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
              >
                Map from JSON
              </button>
              <button
                onClick={() => handleFieldMapping(fieldName, 'fixed', config.mode === 'fixed' ? config.value : '')}
                className={`px-3 py-1 text-xs rounded ${
                  config.mode === 'fixed' 
                    ? 'bg-primary-600 text-white' 
                    : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
              >
                Use Fixed Value
              </button>
              {!isRequired && (
                <button
                  onClick={() => handleFieldMapping(fieldName, 'empty', '')}
                  className={`px-3 py-1 text-xs rounded ${
                    config.mode === 'empty' 
                      ? 'bg-gray-600 text-white' 
                      : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                  }`}
                >
                  Skip
                </button>
              )}
            </div>

            {/* JSON field selector */}
            {config.mode === 'json' && (
              <>
                <select
                  value={config.value}
                  onChange={(e) => handleFieldMapping(fieldName, 'json', e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
                >
                  <option value="">-- Select field from your JSON --</option>
                  {detectedFields.map(field => (
                    <option key={field.name} value={field.name}>
                      {field.name} ({field.type}) - {field.count}/{jsonData.length} items
                    </option>
                  ))}
                </select>
                {config.value && (
                  <p className="text-xs text-gray-600">
                    Sample: <code className="bg-gray-100 px-1 rounded">
                      {JSON.stringify(detectedFields.find(f => f.name === config.value)?.sampleValue).substring(0, 50)}
                    </code>
                  </p>
                )}
              </>
            )}

            {/* Fixed value input */}
            {config.mode === 'fixed' && (
              <>
                <input
                  type="text"
                  value={config.value}
                  onChange={(e) => handleFieldMapping(fieldName, 'fixed', e.target.value)}
                  placeholder={`Enter fixed value (e.g., ${fieldName === 'currency' ? 'INR' : fieldName === 'in_stock' ? 'true' : 'value'})`}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
                />
                <p className="text-xs text-gray-500">
                  💡 This value will be used for all {jsonData.length} items
                </p>
              </>
            )}

            {config.mode === 'empty' && !isRequired && (
              <p className="text-xs text-gray-500 italic">This field will be skipped</p>
            )}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-medium text-gray-900">
          🔄 Map JSON Fields to {contentType === 'product' ? 'Product' : 'Dealer'} Schema
        </h3>
        <p className="mt-1 text-sm text-gray-500">
          Your JSON has different field names. Choose how to map each field below.
        </p>
      </div>

      {/* Detected Fields Summary */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <h4 className="text-sm font-medium text-blue-900 mb-2">
          📋 Detected {detectedFields.length} fields in your JSON ({jsonData.length} items)
        </h4>
        <div className="flex flex-wrap gap-2">
          {detectedFields.slice(0, 10).map(field => (
            <span
              key={field.name}
              className="inline-flex items-center px-2 py-1 rounded text-xs font-mono bg-blue-100 text-blue-800"
            >
              {field.name}
              <span className="ml-1 text-blue-600">({field.type})</span>
            </span>
          ))}
          {detectedFields.length > 10 && (
            <span className="text-xs text-blue-700">...and {detectedFields.length - 10} more</span>
          )}
        </div>
      </div>

      {/* Mapping Options Info */}
      <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
        <h4 className="text-sm font-medium text-yellow-900 mb-2">💡 Mapping Options</h4>
        <ul className="text-xs text-yellow-800 space-y-1">
          <li><strong>Map from JSON:</strong> Use a field from your JSON data</li>
          <li><strong>Use Fixed Value:</strong> Set a constant value for all items (e.g., "INR" for currency)</li>
          <li><strong>Skip:</strong> Leave this optional field empty</li>
        </ul>
      </div>

      {/* Required Field Mappings */}
      <div>
        <h4 className="text-sm font-semibold text-gray-900 mb-4">
          Required Field Mappings <span className="text-red-500">*</span>
        </h4>
        <div className="space-y-3">
          {Object.entries(requiredFields).map(([fieldName, fieldInfo]) => 
            renderFieldMapping(fieldName, fieldInfo, true)
          )}
        </div>
      </div>

      {/* Optional Field Mappings */}
      <details className="border border-gray-200 rounded-lg">
        <summary className="px-4 py-3 cursor-pointer font-medium text-gray-700 hover:bg-gray-50">
          ➕ Optional Field Mappings ({Object.keys(optionalFields).length} available)
        </summary>
        <div className="px-4 py-3 bg-gray-50 border-t border-gray-200 space-y-3">
          {Object.entries(optionalFields).map(([fieldName, fieldInfo]) => 
            renderFieldMapping(fieldName, fieldInfo, false)
          )}
        </div>
      </details>

      {/* Validation Errors */}
      {errors.length > 0 && (
        <div className="rounded-md bg-red-50 p-4">
          <div className="flex">
            <ExclamationTriangleIcon className="h-5 w-5 text-red-400" />
            <div className="ml-3">
              <h3 className="text-sm font-medium text-red-800">
                {errors.length} validation {errors.length === 1 ? 'error' : 'errors'} found
              </h3>
              <div className="mt-2 text-sm text-red-700">
                <ul className="list-disc pl-5 space-y-1">
                  {errors.slice(0, 5).map((error, idx) => (
                    <li key={idx}>{error}</li>
                  ))}
                  {errors.length > 5 && <li>...and {errors.length - 5} more</li>}
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Success State */}
      {errors.length === 0 && Object.keys(mapping).length > 0 && (
        <div className="rounded-md bg-green-50 p-4">
          <div className="flex">
            <CheckCircleIcon className="h-5 w-5 text-green-400" />
            <div className="ml-3">
              <h3 className="text-sm font-medium text-green-800">
                ✅ All required fields mapped successfully!
              </h3>
            </div>
          </div>
        </div>
      )}

      {/* Preview */}
      {previewData.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-gray-900 mb-3">📊 Preview (First 3 Items)</h4>
          <div className="space-y-3">
            {previewData.map((item, idx) => (
              <div key={idx} className="bg-gray-50 border border-gray-200 rounded-lg p-3">
                <div className="text-xs font-mono text-gray-700">
                  <pre className="whitespace-pre-wrap">{JSON.stringify(item, null, 2)}</pre>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Mapping Summary */}
      {Object.keys(mapping).length > 0 && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
          <h4 className="text-sm font-semibold text-gray-900 mb-3">📊 Mapping Summary</h4>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-gray-600">Total Items:</span>
              <span className="ml-2 font-medium text-gray-900">{jsonData.length}</span>
            </div>
            <div>
              <span className="text-gray-600">Required Fields Mapped:</span>
              <span className="ml-2 font-medium text-gray-900">
                {Object.keys(requiredFields).filter(f => mapping[f] && mapping[f].mode !== 'empty').length}/{Object.keys(requiredFields).length}
                {Object.keys(requiredFields).filter(f => mapping[f] && mapping[f].mode !== 'empty').length === Object.keys(requiredFields).length && ' ✅'}
              </span>
            </div>
            <div>
              <span className="text-gray-600">Optional Fields Mapped:</span>
              <span className="ml-2 font-medium text-gray-900">
                {Object.keys(optionalFields).filter(f => mapping[f] && mapping[f].mode !== 'empty').length}/{Object.keys(optionalFields).length}
              </span>
            </div>
            <div>
              <span className="text-gray-600">Validation Status:</span>
              <span className={`ml-2 font-medium ${errors.length === 0 ? 'text-green-600' : 'text-red-600'}`}>
                {errors.length === 0 ? '✅ Valid' : `❌ ${errors.length} errors`}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Action Buttons */}
      <div className="flex justify-between pt-6 border-t border-gray-200">
        <button
          onClick={onBack}
          className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
        >
          ← Back to JSON Upload
        </button>
        <button
          onClick={handleConfirm}
          disabled={errors.length > 0}
          className={`px-6 py-2 text-sm font-medium text-white rounded-md ${
            errors.length === 0
              ? 'bg-primary-600 hover:bg-primary-700'
              : 'bg-gray-300 cursor-not-allowed'
          }`}
        >
          Confirm Mapping & Continue →
        </button>
      </div>
    </div>
  );
}
