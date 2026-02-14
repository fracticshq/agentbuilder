import React, { useState } from 'react';
import { shopifyApi } from '../../api/client';
import { CheckCircleIcon, XCircleIcon, ExclamationTriangleIcon } from '@heroicons/react/24/outline';
import { ArrowPathIcon } from '@heroicons/react/20/solid';

interface ShopifyConfig {
    enabled: boolean;
    shop_url: string;
    storefront_token: string;
    admin_token: string;
}

interface StepShopifyProps {
    data: {
        shopify_config: ShopifyConfig;
    };
    onChange: (field: string, value: any) => void;
}

export default function StepShopify({ data, onChange }: StepShopifyProps) {
    const { shopify_config } = data;
    const [isVerifying, setIsVerifying] = useState(false);
    const [verificationStatus, setVerificationStatus] = useState<'idle' | 'success' | 'error'>('idle');
    const [verificationMessage, setVerificationMessage] = useState('');
    const [shopInfo, setShopInfo] = useState<{ name: string; domain: string } | null>(null);

    const updateConfig = (field: keyof ShopifyConfig, value: any) => {
        onChange('shopify_config', {
            ...shopify_config,
            [field]: value
        });
        // Reset verification status when config changes
        if (verificationStatus !== 'idle') {
            setVerificationStatus('idle');
            setVerificationMessage('');
            setShopInfo(null);
        }
    };

    const handleVerify = async () => {
        if (!shopify_config.shop_url || !shopify_config.storefront_token) {
            setVerificationStatus('error');
            setVerificationMessage('Please enter Shop URL and Storefront Access Token');
            return;
        }

        setIsVerifying(true);
        setVerificationStatus('idle');
        setVerificationMessage('');

        try {
            const result = await shopifyApi.verify({
                shop_url: shopify_config.shop_url,
                storefront_token: shopify_config.storefront_token,
                admin_token: shopify_config.admin_token || undefined
            });

            if (result.data.success) {
                setVerificationStatus('success');
                setShopInfo(result.data.shop);
                setVerificationMessage('Successfully connected to Shopify!');
            }
        } catch (error: any) {
            setVerificationStatus('error');
            const errorMsg = error.response?.data?.detail || error.message || 'Verification failed';
            setVerificationMessage(errorMsg);
        } finally {
            setIsVerifying(false);
        }
    };

    return (
        <div className="space-y-6">
            <div>
                <h3 className="text-lg font-medium text-gray-900">Shopify Integration</h3>
                <p className="mt-1 text-sm text-gray-600">
                    Connect your AI agent to your Shopify store to enable product search, cart management, and order lookup.
                </p>
            </div>

            <div className="flex items-center justify-between py-4 border-t border-b border-gray-200">
                <div className="flex flex-col">
                    <span className="text-sm font-medium text-gray-900">Enable Shopify Integration</span>
                    <span className="text-sm text-gray-500">Allow this agent to access your Shopify store data.</span>
                </div>
                <button
                    type="button"
                    onClick={() => updateConfig('enabled', !shopify_config.enabled)}
                    className={`${shopify_config.enabled ? 'bg-primary-600' : 'bg-gray-200'
                        } relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2`}
                >
                    <span
                        className={`${shopify_config.enabled ? 'translate-x-5' : 'translate-x-0'
                            } pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out`}
                    />
                </button>
            </div>

            {shopify_config.enabled && (
                <div className="space-y-6">
                    <div className="bg-blue-50 border border-blue-200 rounded-md p-4">
                        <div className="flex">
                            <div className="flex-shrink-0">
                                <svg className="h-5 w-5 text-blue-400" viewBox="0 0 20 20" fill="currentColor">
                                    <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
                                </svg>
                            </div>
                            <div className="ml-3">
                                <h3 className="text-sm font-medium text-blue-800">
                                    Prerequisites
                                </h3>
                                <div className="mt-2 text-sm text-blue-700">
                                    <p>You need to create a custom app in your Shopify Admin to get these credentials.</p>
                                    <ul className="list-disc pl-5 mt-1 space-y-1">
                                        <li>Go to Settings {'>'} Apps and sales channels {'>'} Develop apps</li>
                                        <li>Create an app and configure Storefront API scopes (unauthenticated_read_product_listings, unauthenticated_write_checkouts, etc.)</li>
                                        <li>For Admin API, configure Admin API scopes (read_orders, read_products)</li>
                                    </ul>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div>
                        <label htmlFor="shop_url" className="block text-sm font-medium text-gray-700">
                            Shop URL *
                        </label>
                        <div className="mt-1 flex rounded-md shadow-sm">
                            <input
                                type="text"
                                id="shop_url"
                                value={shopify_config.shop_url}
                                onChange={(e) => updateConfig('shop_url', e.target.value)}
                                className="block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
                                placeholder="your-store.myshopify.com"
                            />
                        </div>
                        <p className="mt-1 text-xs text-gray-500">The primary domain of your Shopify store (e.g., store.myshopify.com).</p>
                    </div>

                    <div>
                        <label htmlFor="storefront_token" className="block text-sm font-medium text-gray-700">
                            Storefront API Access Token *
                        </label>
                        <input
                            type="password"
                            id="storefront_token"
                            value={shopify_config.storefront_token}
                            onChange={(e) => updateConfig('storefront_token', e.target.value)}
                            className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
                            placeholder="shpat_..."
                        />
                        <p className="mt-1 text-xs text-gray-500">Required for searching products and managing carts.</p>
                    </div>

                    <div>
                        <label htmlFor="admin_token" className="block text-sm font-medium text-gray-700">
                            Admin API Access Token (Optional)
                        </label>
                        <input
                            type="password"
                            id="admin_token"
                            value={shopify_config.admin_token}
                            onChange={(e) => updateConfig('admin_token', e.target.value)}
                            className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
                            placeholder="shpat_..."
                        />
                        <p className="mt-1 text-xs text-gray-500">Required for looking up order status. Leave blank if not needed.</p>
                    </div>

                    <div className="pt-4 border-t border-gray-200">
                        <div className="flex items-center justify-between">
                            <div>
                                <h4 className="text-sm font-medium text-gray-900">Connection Verification</h4>
                                <p className="text-sm text-gray-500">Test your credentials before saving.</p>
                            </div>
                            <button
                                type="button"
                                onClick={handleVerify}
                                disabled={isVerifying || !shopify_config.shop_url || !shopify_config.storefront_token}
                                className="inline-flex items-center px-4 py-2 border border-gray-300 shadow-sm text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                {isVerifying ? (
                                    <>
                                        <ArrowPathIcon className="animate-spin -ml-1 mr-2 h-4 w-4" />
                                        Verifying...
                                    </>
                                ) : (
                                    'Verify Connection'
                                )}
                            </button>
                        </div>

                        {verificationStatus !== 'idle' && (
                            <div className={`mt-4 p-4 rounded-md ${verificationStatus === 'success' ? 'bg-green-50' : 'bg-red-50'
                                }`}>
                                <div className="flex">
                                    <div className="flex-shrink-0">
                                        {verificationStatus === 'success' ? (
                                            <CheckCircleIcon className="h-5 w-5 text-green-400" aria-hidden="true" />
                                        ) : (
                                            <XCircleIcon className="h-5 w-5 text-red-400" aria-hidden="true" />
                                        )}
                                    </div>
                                    <div className="ml-3">
                                        <h3 className={`text-sm font-medium ${verificationStatus === 'success' ? 'text-green-800' : 'text-red-800'
                                            }`}>
                                            {verificationStatus === 'success' ? 'Connection Successful' : 'Connection Failed'}
                                        </h3>
                                        <div className={`mt-2 text-sm ${verificationStatus === 'success' ? 'text-green-700' : 'text-red-700'
                                            }`}>
                                            <p>{verificationMessage}</p>
                                            {shopInfo && (
                                                <ul className="list-disc pl-5 mt-1 space-y-1">
                                                    <li>Shop Name: {shopInfo.name}</li>
                                                    <li>Domain: {shopInfo.domain}</li>
                                                </ul>
                                            )}
                                        </div>
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
