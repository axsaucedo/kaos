import React from 'react';
import type { UseFormRegister, FieldErrors, FieldValues } from 'react-hook-form';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { validateKubernetesName } from '@/lib/utils';

interface NameFieldProps {
  register: UseFormRegister<FieldValues>;
  errors: FieldErrors;
  placeholder?: string;
  validateUniqueName?: (name: string) => string | true;
}

export function NameField({
  register,
  errors,
  placeholder = 'my-resource',
  validateUniqueName,
}: NameFieldProps) {
  return (
    <div className="space-y-2">
      <Label htmlFor="name">Name</Label>
      <Input
        id="name"
        {...register('name', {
          required: 'Name is required',
          validate: (value) => {
            const k8sValidation = validateKubernetesName(value);
            if (k8sValidation !== true) return k8sValidation;
            return validateUniqueName ? validateUniqueName(value) : true;
          },
        })}
        placeholder={placeholder}
        className="font-mono"
      />
      {errors.name && (
        <p className="text-sm text-destructive">
          {errors.name.message as string}
        </p>
      )}
    </div>
  );
}
