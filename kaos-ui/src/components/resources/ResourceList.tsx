import React, { useState } from 'react';
import { Plus, Search, Edit, Trash2, Eye, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { cn } from '@/lib/utils';

interface Column<T> {
  key: string;
  header: string;
  width?: string;
  render?: (item: T) => React.ReactNode;
}

interface CustomAction<T> {
  label: string;
  icon?: React.ElementType;
  onClick: (item: T) => void;
}

export interface DeploymentAwareStatus {
  label: string;
  variant: 'success' | 'warning' | 'error' | 'destructive' | 'secondary';
  isRolling?: boolean;
  progress?: string; // e.g., "1/2"
}

interface ResourceListProps<T> {
  title: string;
  description: string;
  items: T[];
  columns: Column<T>[];
  icon: React.ElementType;
  iconColor: string;
  onAdd?: () => void;
  onEdit?: (item: T) => void;
  onDelete?: (item: T) => void;
  onView?: (item: T) => void;
  customActions?: CustomAction<T>[];
  getStatus?: (item: T) => string | DeploymentAwareStatus;
  getItemId: (item: T) => string;
}

export function ResourceList<T>({
  title,
  description,
  items,
  columns,
  icon: Icon,
  iconColor,
  onAdd,
  onEdit,
  onDelete,
  onView,
  customActions,
  getStatus,
  getItemId,
}: ResourceListProps<T>) {
  const [search, setSearch] = useState('');
  const [selectedItems, setSelectedItems] = useState<Set<string>>(new Set());
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [itemToDelete, setItemToDelete] = useState<T | null>(null);

  const filteredItems = items.filter((item) => {
    const id = getItemId(item);
    return id.toLowerCase().includes(search.toLowerCase());
  });

  const getStatusVariant = (status: string) => {
    const normalizedStatus = status?.toLowerCase();
    switch (normalizedStatus) {
      case 'running':
      case 'ready':
      case 'bound':
      case 'active':
      case 'available':
        return 'success';
      case 'pending':
      case 'creating':
      case 'waiting':
      case 'progressing':
        return 'warning';
      case 'error':
      case 'failed':
      case 'crashloopbackoff':
        return 'error';
      case 'terminating':
      case 'terminated':
      case 'deleting':
        return 'destructive';
      default:
        return 'secondary';
    }
  };

  const handleDeleteClick = (item: T) => {
    setItemToDelete(item);
    setDeleteDialogOpen(true);
  };

  const handleConfirmDelete = () => {
    if (itemToDelete && onDelete) {
      onDelete(itemToDelete);
    }
    setDeleteDialogOpen(false);
    setItemToDelete(null);
  };

  const handleCancelDelete = () => {
    setDeleteDialogOpen(false);
    setItemToDelete(null);
  };

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div
            className="h-12 w-12 rounded-xl flex items-center justify-center"
            style={{ backgroundColor: `hsl(var(--${iconColor}) / 0.15)` }}
          >
            <Icon className="h-6 w-6" style={{ color: `hsl(var(--${iconColor}))` }} />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-foreground">{title}</h1>
            <p className="text-muted-foreground">{description}</p>
          </div>
        </div>
        <Button onClick={onAdd} className="gap-2">
          <Plus className="h-4 w-4" />
          Create {title.slice(0, -1)}
        </Button>
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-4">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 bg-muted/50 border-transparent"
          />
        </div>
        <Button variant="outline" size="sm" className="gap-2">
          <RefreshCw className="h-4 w-4" />
          Refresh
        </Button>
        <Badge variant="secondary">{filteredItems.length} resources</Badge>
      </div>

      {/* Table */}
      <div className="rounded-xl border border-border overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="bg-muted/50 border-b border-border">
              <th className="w-10 px-4 py-3">
                <input
                  type="checkbox"
                  className="rounded border-border"
                  onChange={(e) => {
                    if (e.target.checked) {
                      setSelectedItems(new Set(filteredItems.map(getItemId)));
                    } else {
                      setSelectedItems(new Set());
                    }
                  }}
                />
              </th>
              {columns.map((col) => (
                <th
                  key={col.key}
                  className={cn(
                    'px-4 py-3 text-left text-xs font-semibold text-muted-foreground uppercase tracking-wider',
                    col.width
                  )}
                >
                  {col.header}
                </th>
              ))}
              {getStatus && (
                <th className="px-4 py-3 text-left text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                  Status
                </th>
              )}
              <th className="px-4 py-3 text-right text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {filteredItems.map((item) => {
              const id = getItemId(item);
              const status = getStatus?.(item);
              return (
                <tr
                  key={id}
                  className={cn(
                    'hover:bg-muted/30 transition-colors',
                    selectedItems.has(id) && 'bg-primary/5'
                  )}
                >
                  <td className="px-4 py-3">
                    <input
                      type="checkbox"
                      className="rounded border-border"
                      checked={selectedItems.has(id)}
                      onChange={(e) => {
                        const newSet = new Set(selectedItems);
                        if (e.target.checked) {
                          newSet.add(id);
                        } else {
                          newSet.delete(id);
                        }
                        setSelectedItems(newSet);
                      }}
                    />
                  </td>
                  {columns.map((col) => (
                    <td key={col.key} className="px-4 py-3">
                      {col.render ? (
                        col.render(item)
                      ) : (
                        <span className="text-sm text-foreground">
                          {(item as any)[col.key]}
                        </span>
                      )}
                    </td>
                  ))}
                  {status && (
                    <td className="px-4 py-3">
                      {typeof status === 'string' ? (
                        <Badge variant={getStatusVariant(status) as any}>{status}</Badge>
                      ) : (
                        <div className="flex items-center gap-2">
                          <Badge variant={status.variant as any} className="gap-1">
                            {status.isRolling && (
                              <RefreshCw className="h-3 w-3 animate-spin" />
                            )}
                            {status.label}
                          </Badge>
                          {status.progress && (
                            <span className="text-xs text-muted-foreground font-mono">
                              {status.progress}
                            </span>
                          )}
                        </div>
                      )}
                    </td>
                  )}
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-1">
                      {/* Custom Actions */}
                      {customActions?.map((action) => {
                        const ActionIcon = action.icon;
                        return (
                          <Tooltip key={action.label}>
                            <TooltipTrigger asChild>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8"
                                onClick={() => action.onClick(item)}
                              >
                                {ActionIcon && <ActionIcon className="h-4 w-4" />}
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>
                              <p>{action.label}</p>
                            </TooltipContent>
                          </Tooltip>
                        );
                      })}

                      {/* View Button */}
                      {onView && (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8"
                              onClick={() => onView(item)}
                            >
                              <Eye className="h-4 w-4" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>
                            <p>View details</p>
                          </TooltipContent>
                        </Tooltip>
                      )}

                      {/* Edit Button */}
                      {onEdit && (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8"
                              onClick={() => onEdit(item)}
                            >
                              <Edit className="h-4 w-4" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>
                            <p>Edit</p>
                          </TooltipContent>
                        </Tooltip>
                      )}

                      {/* Delete Button */}
                      {onDelete && (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8 text-destructive hover:text-destructive hover:bg-destructive/10"
                              onClick={() => handleDeleteClick(item)}
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>
                            <p>Delete</p>
                          </TooltipContent>
                        </Tooltip>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {filteredItems.length === 0 && (
          <div className="p-12 text-center">
            <Icon className="h-12 w-12 mx-auto text-muted-foreground/50 mb-4" />
            <p className="text-muted-foreground">No resources found</p>
            <Button variant="outline" className="mt-4" onClick={onAdd}>
              Create your first resource
            </Button>
          </div>
        )}
      </div>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent className="bg-background border-border">
          <AlertDialogHeader>
            <AlertDialogTitle>Are you sure you want to delete this resource?</AlertDialogTitle>
            <AlertDialogDescription>
              This action cannot be undone. This will permanently delete the resource
              {itemToDelete && (
                <span className="font-mono font-medium text-foreground">
                  {' '}{getItemId(itemToDelete)}
                </span>
              )}
              {' '}from the Kubernetes cluster.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={handleCancelDelete}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmDelete}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
