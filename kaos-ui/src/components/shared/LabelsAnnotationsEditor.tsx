import React from 'react';
import { UseFormRegister, useFieldArray, Control } from 'react-hook-form';
import { Plus, Trash2, Tag } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';

interface LabelsAnnotationsEditorProps {
  control: Control<any>;
  register: UseFormRegister<any>;
  labelsFieldName?: string;
  annotationsFieldName?: string;
}

export function LabelsAnnotationsEditor({
  control,
  register,
  labelsFieldName = 'labels',
  annotationsFieldName = 'annotations',
}: LabelsAnnotationsEditorProps) {
  const {
    fields: labelFields,
    append: appendLabel,
    remove: removeLabel,
  } = useFieldArray({ control, name: labelsFieldName });

  const {
    fields: annotationFields,
    append: appendAnnotation,
    remove: removeAnnotation,
  } = useFieldArray({ control, name: annotationsFieldName });

  return (
    <Collapsible>
      <CollapsibleTrigger asChild>
        <Button variant="ghost" type="button" className="w-full justify-between px-0 hover:bg-transparent">
          <Label className="flex items-center gap-2 cursor-pointer">
            <Tag className="h-4 w-4" />
            Labels & Annotations
          </Label>
          <span className="text-xs text-muted-foreground">
            {labelFields.length + annotationFields.length} items
          </span>
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent className="space-y-4 pt-4">
        {/* Labels */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label className="text-sm">Labels</Label>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => appendLabel({ key: '', value: '' })}
            >
              <Plus className="h-3 w-3 mr-1" />
              Add Label
            </Button>
          </div>
          {labelFields.length > 0 && (
            <div className="space-y-2">
              {labelFields.map((field, index) => (
                <div key={field.id} className="flex gap-2">
                  <Input
                    {...register(`${labelsFieldName}.${index}.key` as const)}
                    placeholder="key"
                    className="font-mono text-xs"
                  />
                  <Input
                    {...register(`${labelsFieldName}.${index}.value` as const)}
                    placeholder="value"
                    className="font-mono text-xs"
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => removeLabel(index)}
                  >
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Annotations */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label className="text-sm">Annotations</Label>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => appendAnnotation({ key: '', value: '' })}
            >
              <Plus className="h-3 w-3 mr-1" />
              Add Annotation
            </Button>
          </div>
          {annotationFields.length > 0 && (
            <div className="space-y-2">
              {annotationFields.map((field, index) => (
                <div key={field.id} className="flex gap-2">
                  <Input
                    {...register(`${annotationsFieldName}.${index}.key` as const)}
                    placeholder="key"
                    className="font-mono text-xs"
                  />
                  <Input
                    {...register(`${annotationsFieldName}.${index}.value` as const)}
                    placeholder="value"
                    className="font-mono text-xs flex-1"
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => removeAnnotation(index)}
                  >
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
