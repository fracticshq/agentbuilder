import React, { useCallback, useState } from 'react';
import { DocumentArrowUpIcon, XMarkIcon } from '@heroicons/react/24/outline';

interface FileUploadProps {
  onFilesSelected: (files: File[]) => void;
  accept?: string;
  multiple?: boolean;
  maxSizeMB?: number;
}

export default function FileUpload({
  onFilesSelected,
  accept = '.pdf,.docx,.txt,.md,.html,.json',
  multiple = true,
  maxSizeMB = 10,
}: FileUploadProps) {
  const [dragActive, setDragActive] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [errors, setErrors] = useState<string[]>([]);

  const maxSizeBytes = maxSizeMB * 1024 * 1024;

  const validateFiles = (files: File[]): { valid: File[]; errors: string[] } => {
    const valid: File[] = [];
    const errors: string[] = [];

    files.forEach(file => {
      // Check file size
      if (file.size > maxSizeBytes) {
        errors.push(`${file.name}: File size exceeds ${maxSizeMB}MB limit`);
        return;
      }

      // Check file type
      const extension = '.' + file.name.split('.').pop()?.toLowerCase();
      const acceptedTypes = accept.split(',').map(t => t.trim());
      
      if (!acceptedTypes.includes(extension)) {
        errors.push(`${file.name}: File type not supported. Accepted: ${accept}`);
        return;
      }

      valid.push(file);
    });

    return { valid, errors };
  };

  const handleFiles = (files: FileList | null) => {
    if (!files || files.length === 0) return;

    const fileArray = Array.from(files);
    const { valid, errors: validationErrors } = validateFiles(fileArray);

    setErrors(validationErrors);

    if (valid.length > 0) {
      const newFiles = multiple 
        ? [...selectedFiles, ...valid]
        : valid;
      
      setSelectedFiles(newFiles);
      onFilesSelected(newFiles);
    }
  };

  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  }, []);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFiles(e.dataTransfer.files);
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    e.preventDefault();
    handleFiles(e.target.files);
  };

  const removeFile = (index: number) => {
    const newFiles = selectedFiles.filter((_, i) => i !== index);
    setSelectedFiles(newFiles);
    onFilesSelected(newFiles);
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  };

  return (
    <div className="w-full">
      {/* Upload Zone */}
      <div
        className={`
          relative border-2 border-dashed rounded-lg p-12 text-center transition-colors
          ${dragActive 
            ? 'border-primary-500 bg-primary-50' 
            : 'border-gray-300 hover:border-gray-400'
          }
        `}
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
      >
        <input
          type="file"
          id="file-upload"
          className="hidden"
          onChange={handleChange}
          accept={accept}
          multiple={multiple}
        />
        
        <DocumentArrowUpIcon className="mx-auto h-12 w-12 text-gray-400" />
        
        <div className="mt-4">
          <label
            htmlFor="file-upload"
            className="cursor-pointer font-medium text-primary-600 hover:text-primary-500"
          >
            <span>Click to upload</span>
          </label>
          <span className="text-gray-600"> or drag and drop</span>
        </div>
        
        <p className="mt-2 text-sm text-gray-500">
          Supported: PDF, DOCX, TXT, MD, HTML, JSON
        </p>
        
        <p className="mt-1 text-xs text-gray-400">
          Max file size: {maxSizeMB}MB
        </p>
      </div>

      {/* Error Messages */}
      {errors.length > 0 && (
        <div className="mt-4 rounded-md bg-red-50 p-4">
          <div className="flex">
            <div className="ml-3">
              <h3 className="text-sm font-medium text-red-800">
                Upload errors
              </h3>
              <div className="mt-2 text-sm text-red-700">
                <ul className="list-disc space-y-1 pl-5">
                  {errors.map((error, index) => (
                    <li key={index}>{error}</li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Selected Files List */}
      {selectedFiles.length > 0 && (
        <div className="mt-6">
          <h4 className="text-sm font-medium text-gray-900 mb-3">
            📂 Selected Files ({selectedFiles.length})
          </h4>
          
          <ul className="divide-y divide-gray-200 rounded-md border border-gray-200">
            {selectedFiles.map((file, index) => (
              <li
                key={index}
                className="flex items-center justify-between py-3 px-4 text-sm"
              >
                <div className="flex items-center flex-1 min-w-0">
                  <DocumentArrowUpIcon className="h-5 w-5 text-gray-400 flex-shrink-0" />
                  <span className="ml-3 truncate font-medium text-gray-900">
                    {file.name}
                  </span>
                  <span className="ml-3 text-gray-500">
                    ({formatFileSize(file.size)})
                  </span>
                </div>
                
                <button
                  onClick={() => removeFile(index)}
                  className="ml-4 flex-shrink-0 text-gray-400 hover:text-red-500"
                >
                  <XMarkIcon className="h-5 w-5" />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
