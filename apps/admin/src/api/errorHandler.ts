import axios, { AxiosError } from 'axios';

/**
 * Error handler for API calls
 * Provides consistent error messages to users
 */
export class ApiError extends Error {
  public statusCode?: number;
  public details?: string;

  constructor(message: string, statusCode?: number, details?: string) {
    super(message);
    this.name = 'ApiError';
    this.statusCode = statusCode;
    this.details = details;
  }
}

/**
 * Handle API errors and convert them to ApiError with user-friendly messages
 */
export function handleApiError(error: unknown): ApiError {
  console.error('API Error:', error);

  if (axios.isAxiosError(error)) {
    const axiosError = error as AxiosError<{ detail?: string; message?: string }>;
    
    // Network error (API server not running)
    if (axiosError.code === 'ERR_NETWORK' || !axiosError.response) {
      return new ApiError(
        'Cannot connect to the server. Please ensure the API server is running.',
        503,
        'The API server at ' + (axiosError.config?.baseURL || 'localhost:8000') + ' is not reachable.'
      );
    }

    // Server returned an error response
    const status = axiosError.response?.status || 500;
    const detail = axiosError.response?.data?.detail || axiosError.response?.data?.message;
    
    switch (status) {
      case 400:
        return new ApiError('Invalid request. Please check your input.', status, detail);
      case 401:
        return new ApiError('Authentication required. Please log in.', status, detail);
      case 403:
        return new ApiError('You do not have permission to perform this action.', status, detail);
      case 404:
        return new ApiError('The requested resource was not found.', status, detail);
      case 409:
        return new ApiError('A conflict occurred. This resource may already exist.', status, detail);
      case 422:
        return new ApiError('Validation error. Please check your input.', status, detail);
      case 500:
      case 502:
      case 503:
        return new ApiError('Server error. Please try again later.', status, detail);
      default:
        return new ApiError(`Request failed with status ${status}`, status, detail);
    }
  }

  // Unknown error type
  if (error instanceof Error) {
    return new ApiError(error.message);
  }

  return new ApiError('An unexpected error occurred');
}

/**
 * Show user-friendly error alert
 */
export function showErrorAlert(error: ApiError | Error) {
  if (error instanceof ApiError) {
    const message = error.details 
      ? `${error.message}\n\nDetails: ${error.details}`
      : error.message;
    alert(message);
  } else {
    alert(error.message || 'An unexpected error occurred');
  }
}
