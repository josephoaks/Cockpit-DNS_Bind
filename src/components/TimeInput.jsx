import React from 'react';
import { TextInput } from '@patternfly/react-core';

export const TIME_UNITS = [
  { value: 's', label: 'Seconds' },
  { value: 'm', label: 'Minutes' },
  { value: 'h', label: 'Hours' },
  { value: 'd', label: 'Days' },
  { value: 'w', label: 'Weeks' }
];

export const TimeInput = ({ value, unit, onValueChange, onUnitChange, id }) => {
  return (
    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
      <TextInput
        type="number"
        id={`${id}-value`}
        value={value}
        onChange={onValueChange}
        style={{ width: '80px', flex: 'none' }}
      />
      <select
        id={`${id}-unit`}
        className="pf-v6-c-form-control"
        style={{ 
          width: '120px', 
          flex: 'none',
          display: 'flex',
          alignItems: 'center'
        }}
        value={unit}
        onChange={onUnitChange}
      >
        {TIME_UNITS.map(u => (
          <option key={u.value} value={u.value}>{u.label}</option>
        ))}
      </select>
    </div>
  );
};
