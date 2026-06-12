import React, { useEffect, useMemo, useState } from 'react';
import {
  ArrowPathIcon,
  ArrowRightIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  DocumentTextIcon,
  FolderIcon,
  FolderOpenIcon,
  MagnifyingGlassIcon,
  PencilIcon,
  PlayIcon,
  PlusIcon,
  TrashIcon,
} from '@heroicons/react/24/outline';
import { knowledgeApi } from '../../api/knowledge';
import type {
  DocumentSummary,
  KnowledgeFolderNode,
  KnowledgeFolderSelection,
  KnowledgeItem,
  KnowledgeItemStatus,
  RetrievedKnowledgeChunk,
} from '../../types/knowledge';

interface KnowledgeExplorerProps {
  brandId: string;
  brandName?: string;
  agentId?: string;
  agentName?: string;
  mode?: 'workspace' | 'agent';
  onUpload: (folder: KnowledgeFolderSelection) => void;
}

const ROOT_FOLDER: KnowledgeFolderNode = {
  id: null,
  name: 'Knowledge Base',
  path: '/',
  children: [],
  items: [],
  documents: [],
};

function normalizePath(path?: string): string {
  if (!path || path === '') return '/';
  const withSlash = path.startsWith('/') ? path : `/${path}`;
  return withSlash.length > 1 ? withSlash.replace(/\/+$/, '') : '/';
}

function folderNameFromPath(path: string): string {
  if (path === '/') return 'Knowledge Base';
  return path.split('/').filter(Boolean).pop() || path;
}

function documentToItem(doc: DocumentSummary): KnowledgeItem {
  const folderPath = normalizePath(doc.folder_path || doc.path || '/');
  const name = doc.title || doc.doc_id;

  return {
    id: doc.doc_id,
    name,
    kind: 'document',
    path: folderPath === '/' ? `/${name}` : `${folderPath}/${name}`,
    parent_id: doc.folder_id || null,
    content_type: doc.content_type,
    chunks_count: doc.chunks_count,
    item_count: doc.item_count,
    status: (doc.status || 'ready') as KnowledgeItemStatus,
    created_at: doc.created_at,
    source_doc_id: doc.doc_id,
  };
}

function normalizeItem(item: KnowledgeItem): KnowledgeItem {
  return {
    ...item,
    id: item.id || item.source_doc_id || item.path,
    name: item.name || folderNameFromPath(item.path),
    path: normalizePath(item.path),
    kind: item.kind || 'document',
    status: item.status || 'ready',
  };
}

function normalizeNode(node?: Partial<KnowledgeFolderNode>): KnowledgeFolderNode {
  const path = normalizePath(node?.path || '/');

  return {
    id: node?.id ?? (path === '/' ? null : path),
    name: node?.name || folderNameFromPath(path),
    path,
    parent_id: node?.parent_id ?? null,
    children: (node?.children || []).map(normalizeNode),
    items: (node?.items || []).map(normalizeItem),
    documents: node?.documents || [],
  };
}

function treeFromDocuments(documents: DocumentSummary[]): KnowledgeFolderNode {
  return {
    ...ROOT_FOLDER,
    items: documents.map(documentToItem),
  };
}

function flattenFolders(root: KnowledgeFolderNode): KnowledgeFolderNode[] {
  return [root, ...(root.children || []).flatMap(flattenFolders)];
}

function findFolder(root: KnowledgeFolderNode, path: string): KnowledgeFolderNode | null {
  if (root.path === path) return root;
  for (const child of root.children || []) {
    const match = findFolder(child, path);
    if (match) return match;
  }
  return null;
}

function formatDate(value?: string): string {
  if (!value) return 'Unknown';
  try {
    return new Date(value).toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  } catch {
    return value;
  }
}

function itemTone(type?: string): string {
  const tones: Record<string, string> = {
    product: 'bg-sky-50 text-sky-700 ring-sky-200',
    dealer: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
    faq: 'bg-amber-50 text-amber-700 ring-amber-200',
    guide: 'bg-indigo-50 text-indigo-700 ring-indigo-200',
    document: 'bg-gray-50 text-gray-700 ring-gray-200',
  };
  return tones[type || 'document'] || tones.document;
}

function metricLabel(item: KnowledgeItem): string {
  const parts = [];
  if (typeof item.item_count === 'number') parts.push(`${item.item_count} items`);
  if (typeof item.chunks_count === 'number') parts.push(`${item.chunks_count} chunks`);
  return parts.join(' / ') || 'No chunks yet';
}

function FolderTreeRow({
  node,
  depth,
  selectedPath,
  expandedPaths,
  onSelect,
  onToggle,
}: {
  node: KnowledgeFolderNode;
  depth: number;
  selectedPath: string;
  expandedPaths: Set<string>;
  onSelect: (folder: KnowledgeFolderNode) => void;
  onToggle: (path: string) => void;
}) {
  const hasChildren = (node.children || []).length > 0;
  const expanded = expandedPaths.has(node.path);
  const selected = selectedPath === node.path;

  return (
    <div>
      <div className="flex items-center">
        <button
          type="button"
          onClick={() => hasChildren && onToggle(node.path)}
          className="flex h-7 w-5 items-center justify-center text-gray-400 hover:text-gray-700"
          aria-label={expanded ? `Collapse ${node.name}` : `Expand ${node.name}`}
        >
          {hasChildren ? (
            expanded ? <ChevronDownIcon className="h-4 w-4" /> : <ChevronRightIcon className="h-4 w-4" />
          ) : null}
        </button>
        <button
          type="button"
          onClick={() => onSelect(node)}
          className={`group flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm ${
            selected
              ? 'bg-gray-900 text-white'
              : 'text-gray-700 hover:bg-gray-100'
          }`}
          style={{ marginLeft: depth * 10 }}
        >
          {selected ? (
            <FolderOpenIcon className="h-4 w-4 flex-none" />
          ) : (
            <FolderIcon className="h-4 w-4 flex-none text-gray-400 group-hover:text-gray-600" />
          )}
          <span className="truncate">{node.name}</span>
        </button>
      </div>
      {expanded && (node.children || []).map((child) => (
        <FolderTreeRow
          key={child.id || child.path}
          node={child}
          depth={depth + 1}
          selectedPath={selectedPath}
          expandedPaths={expandedPaths}
          onSelect={onSelect}
          onToggle={onToggle}
        />
      ))}
    </div>
  );
}

export default function KnowledgeExplorer({
  brandId,
  brandName,
  agentId,
  agentName,
  mode = 'workspace',
  onUpload,
}: KnowledgeExplorerProps) {
  const [tree, setTree] = useState<KnowledgeFolderNode>(ROOT_FOLDER);
  const [selectedPath, setSelectedPath] = useState('/');
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set(['/']));
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busyItemId, setBusyItemId] = useState<string | null>(null);
  const [retrieveQuery, setRetrieveQuery] = useState('');
  const [retrieveTopK, setRetrieveTopK] = useState(5);
  const [retrievalType, setRetrievalType] = useState('Basic');
  const [scoreThreshold, setScoreThreshold] = useState(0);
  const [retrieving, setRetrieving] = useState(false);
  const [retrieveError, setRetrieveError] = useState<string | null>(null);
  const [retrieveResults, setRetrieveResults] = useState<RetrievedKnowledgeChunk[]>([]);

  const selectedFolder = useMemo(() => findFolder(tree, selectedPath) || tree, [tree, selectedPath]);
  const folders = useMemo(() => flattenFolders(tree), [tree]);

  const currentItems = useMemo(() => {
    const folderItems = (selectedFolder.items || []).map(normalizeItem);
    const documentItems = (selectedFolder.documents || []).map(documentToItem);
    const byId = new Map<string, KnowledgeItem>();

    [...(selectedFolder.children || []).map(child => ({
      id: child.id || child.path,
      name: child.name,
      kind: 'folder' as const,
      path: child.path,
      parent_id: child.parent_id || selectedFolder.id,
      status: 'ready' as const,
      updated_at: child.items?.[0]?.updated_at,
    })), ...folderItems, ...documentItems].forEach(item => {
      byId.set(item.id, item);
    });

    const query = search.trim().toLowerCase();
    return Array.from(byId.values())
      .filter(item => !query || `${item.name} ${item.content_type || ''} ${item.path}`.toLowerCase().includes(query))
      .sort((a, b) => {
        if (a.kind !== b.kind) return a.kind === 'folder' ? -1 : 1;
        return a.name.localeCompare(b.name);
      });
  }, [selectedFolder, search]);

  const totals = useMemo(() => {
    const allItems = folders.flatMap(folder => [
      ...(folder.items || []),
      ...(folder.documents || []).map(documentToItem),
    ]);

    return {
      folders: Math.max(0, folders.length - 1),
      documents: allItems.filter(item => item.kind !== 'folder').length,
      chunks: allItems.reduce((sum, item) => sum + (item.chunks_count || 0), 0),
    };
  }, [folders]);

  const loadTree = async () => {
    setLoading(true);
    setError(null);
    setNotice(null);

    try {
      const response = await knowledgeApi.getTree(brandId);
      const nextTree = normalizeNode(response.root || ROOT_FOLDER);
      const rootItems = (response.items || []).map(normalizeItem);
      const rootDocuments = response.documents || [];
      nextTree.items = [...(nextTree.items || []), ...rootItems];
      nextTree.documents = [...(nextTree.documents || []), ...rootDocuments];
      setTree(nextTree);
      if (!findFolder(nextTree, selectedPath)) {
        setSelectedPath('/');
      }
    } catch (treeError: any) {
      try {
        const docs = await knowledgeApi.getDocuments(brandId);
        setTree(treeFromDocuments(docs));
        setSelectedPath('/');
        setNotice('Tree endpoint unavailable. Showing legacy documents under /.');
      } catch (documentsError: any) {
        setError(documentsError?.message || treeError?.message || 'Failed to load knowledge base');
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadTree();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId]);

  const selectedFolderRef: KnowledgeFolderSelection = {
    id: selectedFolder.id,
    path: selectedFolder.path,
    name: selectedFolder.name,
  };

  const toggleFolder = (path: string) => {
    setExpandedPaths(prev => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  };

  const selectFolder = (folder: KnowledgeFolderNode) => {
    setSelectedPath(folder.path);
    setExpandedPaths(prev => new Set(prev).add(folder.path));
  };

  const handleCreateFolder = async () => {
    const name = window.prompt('Folder name');
    if (!name?.trim()) return;

    try {
      setBusyItemId('new-folder');
      await knowledgeApi.createFolder({
        name: name.trim(),
        brand_id: brandId,
        parent_id: selectedFolder.id || null,
        parent_path: selectedFolder.path,
      });
      await loadTree();
    } catch (createError: any) {
      setError(createError?.message || 'Failed to create folder');
    } finally {
      setBusyItemId(null);
    }
  };

  const handleRename = async (item: KnowledgeItem) => {
    const name = window.prompt('New name', item.name);
    if (!name?.trim() || name.trim() === item.name) return;

    try {
      setBusyItemId(item.id);
      await knowledgeApi.renameItem(item.id, { name: name.trim(), brand_id: brandId });
      await loadTree();
    } catch (renameError: any) {
      setError(renameError?.message || 'Failed to rename item');
    } finally {
      setBusyItemId(null);
    }
  };

  const handleMove = async (item: KnowledgeItem) => {
    const folderPath = window.prompt('Move to folder path', selectedFolder.path);
    if (!folderPath) return;

    try {
      setBusyItemId(item.id);
      await knowledgeApi.moveItem(item.id, {
        brand_id: brandId,
        folder_path: normalizePath(folderPath),
      });
      await loadTree();
    } catch (moveError: any) {
      setError(moveError?.message || 'Failed to move item');
    } finally {
      setBusyItemId(null);
    }
  };

  const handleDelete = async (item: KnowledgeItem) => {
    if (!window.confirm(`Delete "${item.name}"? This cannot be undone.`)) return;

    try {
      setBusyItemId(item.id);
      await knowledgeApi.deleteItem(item.id, brandId);
      await loadTree();
    } catch (deleteError: any) {
      setError(deleteError?.message || 'Failed to delete item');
    } finally {
      setBusyItemId(null);
    }
  };

  const handleRetrieve = async () => {
    if (!retrieveQuery.trim()) {
      setRetrieveError('Enter a query to test retrieval.');
      return;
    }

    try {
      setRetrieving(true);
      setRetrieveError(null);
      const retrievePayload = {
        query: retrieveQuery.trim(),
        brand_id: brandId,
        ...(agentId ? { agent_id: agentId } : {}),
        folder_id: selectedFolder.id || null,
        folder_path: selectedFolder.path,
        top_k: retrieveTopK,
        ...(scoreThreshold > 0 ? { score_threshold: scoreThreshold } : {}),
      };
      const response = await knowledgeApi.retrieve(retrievePayload);
      setRetrieveResults(response.results || []);
    } catch (retrieveFailure: any) {
      setRetrieveError(retrieveFailure?.message || 'Retrieval failed');
    } finally {
      setRetrieving(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 border-b border-gray-200 pb-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-center gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-semibold tracking-tight text-gray-950">Knowledge Base</h1>
              <span className="rounded bg-gray-100 px-2 py-1 text-xs font-medium text-gray-600">context filesystem</span>
              <span className="rounded bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700">
                {mode === 'agent' ? 'Agent Attached Knowledge' : 'Workspace Knowledge Library'}
              </span>
            </div>
            <p className="mt-1 text-sm text-gray-500">
              {mode === 'agent' && agentName
                ? `Managing sources attached to ${agentName} in ${brandName || brandId}.`
                : `Managing reusable sources for ${brandName || brandId}. Attach relevant folders or files from the agent builder.`}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            aria-label="Upload file"
            onClick={() => onUpload(selectedFolderRef)}
            className="inline-flex items-center rounded-md border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-800 shadow-sm hover:bg-gray-50"
          >
            <PlusIcon className="mr-1.5 h-4 w-4" />
            Add File
          </button>
          <button
            type="button"
            disabled
            className="inline-flex items-center rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            <PlusIcon className="mr-1.5 h-4 w-4" />
            Add Website
          </button>
          <button
            type="button"
            disabled
            className="inline-flex items-center rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            <PlusIcon className="mr-1.5 h-4 w-4" />
            Add Text
          </button>
          <button
            type="button"
            disabled
            className="inline-flex items-center rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            <PlusIcon className="mr-1.5 h-4 w-4" />
            Add Live Source
          </button>
          <button
            type="button"
            onClick={handleCreateFolder}
            disabled={busyItemId === 'new-folder'}
            className="inline-flex items-center rounded-md border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            <FolderIcon className="mr-1.5 h-4 w-4" />
            Folder
          </button>
          <button
            type="button"
            onClick={loadTree}
            className="inline-flex items-center rounded-md border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            <ArrowPathIcon className="mr-1.5 h-4 w-4" />
            Refresh
          </button>
        </div>
      </div>

      <div className="grid gap-3 border-y border-gray-200 bg-white py-3 sm:grid-cols-3">
        <div className="px-1">
          <p className="text-xs font-medium uppercase tracking-wide text-gray-500">Folders</p>
          <p className="font-mono text-2xl font-semibold text-gray-950">{totals.folders}</p>
        </div>
        <div className="px-1">
          <p className="text-xs font-medium uppercase tracking-wide text-gray-500">Files</p>
          <p className="font-mono text-2xl font-semibold text-gray-950">{totals.documents}</p>
        </div>
        <div className="px-1">
          <p className="text-xs font-medium uppercase tracking-wide text-gray-500">Chunks</p>
          <p className="font-mono text-2xl font-semibold text-gray-950">{totals.chunks}</p>
        </div>
      </div>

      {notice && (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {notice}
        </div>
      )}
      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid min-h-[620px] gap-4 lg:grid-cols-[220px_minmax(0,1fr)_390px]">
        <aside className="overflow-hidden rounded-lg border border-gray-200 bg-white">
          <div className="border-b border-gray-200 px-3 py-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Folders</p>
          </div>
          <div className="max-h-[560px] overflow-auto p-2">
            {loading ? (
              <div className="space-y-2 p-2">
                <div className="h-7 rounded bg-gray-100" />
                <div className="h-7 rounded bg-gray-100" />
                <div className="h-7 rounded bg-gray-100" />
              </div>
            ) : (
              <FolderTreeRow
                node={tree}
                depth={0}
                selectedPath={selectedFolder.path}
                expandedPaths={expandedPaths}
                onSelect={selectFolder}
                onToggle={toggleFolder}
              />
            )}
          </div>
        </aside>

        <main className="overflow-hidden rounded-lg border border-gray-200 bg-white">
          <div className="flex flex-col gap-3 border-b border-gray-200 px-4 py-3 xl:flex-row xl:items-center xl:justify-between">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-sm text-gray-500">
                <FolderOpenIcon className="h-4 w-4" />
                <span className="truncate font-mono text-gray-700">{selectedFolder.path}</span>
              </div>
              <p className="mt-1 text-xs text-gray-500">
                {currentItems.length} item{currentItems.length === 1 ? '' : 's'} in selected folder
              </p>
            </div>
            <label className="relative block w-full xl:w-72">
              <MagnifyingGlassIcon className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-gray-400" />
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search files..."
                className="w-full rounded-md border border-gray-300 py-2 pl-9 pr-3 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
              />
            </label>
          </div>

          <div className="overflow-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
                <tr>
                  <th className="px-4 py-2">Name</th>
                  <th className="px-3 py-2">Type</th>
                  <th className="px-3 py-2">Contents</th>
                  <th className="px-3 py-2">Updated</th>
                  <th className="px-4 py-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {loading ? (
                  Array.from({ length: 6 }).map((_, index) => (
                    <tr key={index}>
                      <td className="px-4 py-3" colSpan={5}>
                        <div className="h-5 rounded bg-gray-100" />
                      </td>
                    </tr>
                  ))
                ) : currentItems.length === 0 ? (
                  <tr>
                    <td className="px-4 py-12 text-center text-sm text-gray-500" colSpan={5}>
                      No files in this folder.
                    </td>
                  </tr>
                ) : currentItems.map((item) => (
                  <tr key={item.id} className="hover:bg-gray-50">
                    <td className="px-4 py-2.5">
                      <button
                        type="button"
                        onClick={() => {
                          if (item.kind === 'folder') {
                            const folder = findFolder(tree, item.path);
                            if (folder) selectFolder(folder);
                          }
                        }}
                        className="flex max-w-[360px] items-center gap-2 text-left font-medium text-gray-900"
                      >
                        {item.kind === 'folder' ? (
                          <FolderIcon className="h-5 w-5 flex-none text-gray-400" />
                        ) : (
                          <DocumentTextIcon className="h-5 w-5 flex-none text-gray-400" />
                        )}
                        <span className="truncate">{item.name}</span>
                      </button>
                    </td>
                    <td className="px-3 py-2.5">
                      <span className={`inline-flex rounded px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${itemTone(item.content_type || item.kind)}`}>
                        {item.content_type || item.kind}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-xs text-gray-500">{item.kind === 'folder' ? item.path : metricLabel(item)}</td>
                    <td className="px-3 py-2.5 text-xs text-gray-500">{formatDate(item.updated_at || item.created_at)}</td>
                    <td className="px-4 py-2.5">
                      <div className="flex justify-end gap-1">
                        <button
                          type="button"
                          onClick={() => handleRename(item)}
                          disabled={busyItemId === item.id}
                          className="rounded p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-900 disabled:opacity-50"
                          aria-label={`Rename ${item.name}`}
                          title="Rename"
                        >
                          <PencilIcon className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          onClick={() => handleMove(item)}
                          disabled={busyItemId === item.id}
                          className="rounded p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-900 disabled:opacity-50"
                          aria-label={`Move ${item.name}`}
                          title="Move"
                        >
                          <ArrowRightIcon className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDelete(item)}
                          disabled={busyItemId === item.id}
                          className="rounded p-1.5 text-red-500 hover:bg-red-50 hover:text-red-700 disabled:opacity-50"
                          aria-label={`Delete ${item.name}`}
                          title="Delete"
                        >
                          <TrashIcon className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </main>

        <aside className="rounded-lg border border-gray-200 bg-white">
          <div className="border-b border-gray-200 px-4 py-4">
            <p className="text-sm font-semibold text-gray-900">Knowledge Base Retrieval</p>
            <p className="mt-1 text-xs leading-5 text-gray-500">
              Search through your knowledge base by entering a query below. The system will retrieve the most relevant chunks of information.
            </p>
          </div>
          <div className="space-y-3 p-4">
            <label className="block">
              <span className="text-xs font-medium text-gray-700">Query</span>
              <textarea
                value={retrieveQuery}
                onChange={(event) => setRetrieveQuery(event.target.value)}
                rows={4}
                className="mt-1 w-full resize-none rounded-md border border-gray-300 px-3 py-2 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
                placeholder="Ask what this folder should answer"
              />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="text-xs font-medium text-gray-700">Number of Chunks</span>
                <input
                  type="number"
                  min={1}
                  max={50}
                  value={retrieveTopK}
                  onChange={(event) => setRetrieveTopK(Number(event.target.value) || 1)}
                  className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
                />
              </label>
              <label className="block">
                <span className="text-xs font-medium text-gray-700">Retrieval Type</span>
                <select
                  value={retrievalType}
                  onChange={(event) => setRetrievalType(event.target.value)}
                  className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm outline-none focus:border-gray-500 focus:ring-1 focus:ring-gray-500"
                >
                  <option>Basic</option>
                  <option>Semantic</option>
                  <option>Hybrid</option>
                </select>
              </label>
            </div>
            <label className="block">
              <span className="text-xs font-medium text-gray-700">Score Threshold: {scoreThreshold.toFixed(1)}</span>
              <input
                type="range"
                min={0}
                max={1}
                step={0.1}
                value={scoreThreshold}
                onChange={(event) => setScoreThreshold(Number(event.target.value))}
                className="mt-2 w-full"
              />
            </label>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setRetrieveQuery('');
                  setRetrieveResults([]);
                  setRetrieveError(null);
                }}
                className="rounded-md border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Reset
              </button>
              <button
                type="button"
                aria-label="Test Retrieval"
                onClick={handleRetrieve}
                disabled={retrieving}
                className="inline-flex items-center justify-center rounded-md bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-400"
              >
                {retrieving ? (
                  <ArrowPathIcon className="mr-1.5 h-4 w-4 animate-spin" />
                ) : (
                  <PlayIcon className="mr-1.5 h-4 w-4" />
                )}
                Retrieve
              </button>
            </div>
            {retrieveError && (
              <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{retrieveError}</p>
            )}
            <div className="space-y-2">
              <p className="px-1 text-sm font-semibold text-gray-900">Retrieved Chunks</p>
              {retrieveResults.length === 0 ? (
                <div className="rounded-md border border-dashed border-gray-300 px-3 py-8 text-center text-sm text-gray-500">
                  Results will appear here.
                </div>
              ) : retrieveResults.map((result, index) => (
                <div key={result.id || `${result.doc_id}-${index}`} className="rounded-md border border-gray-200 p-3">
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <p className="truncate text-sm font-medium text-gray-900">{result.title || result.doc_id || `Result ${index + 1}`}</p>
                    {typeof result.score === 'number' && (
                      <span className="font-mono text-xs text-gray-500">{result.score.toFixed(3)}</span>
                    )}
                  </div>
                  <p className="line-clamp-4 text-xs leading-5 text-gray-600">{result.content}</p>
                  {result.path && <p className="mt-2 truncate font-mono text-[11px] text-gray-400">{result.path}</p>}
                </div>
              ))}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
