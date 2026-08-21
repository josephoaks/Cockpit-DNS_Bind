import React from 'react';
import {
  Tabs,
  Tab,
  TabTitleText,
} from '@patternfly/react-core';

import './app.scss';
import { ZonesPage } from './components/ZonesPage';
import { TsigKeysPage } from './components/TsigKeysPage';
import { AclsPage } from './components/AclsPage';
import { ForwardersPage } from './components/ForwardersPage';
import { BackupsPage } from './components/BackupsPage';
import { LoggingPage } from './components/LoggingPage';

export const Application = () => {
  const [activeTabKey, setActiveTabKey] = React.useState(0);

  const handleTabClick = (event, tabIndex) => {
    setActiveTabKey(tabIndex);
  };

  React.useEffect(() => {
    const handleNavigate = (event) => {
      setActiveTabKey(event.detail.tabIndex);
    };

    window.addEventListener('navigate-to-tab', handleNavigate);
    return () => window.removeEventListener('navigate-to-tab', handleNavigate);
  }, []);

  return (
    <Tabs
      activeKey={activeTabKey}
      onSelect={handleTabClick}
      aria-label="DNS Server Configuration Tabs"
      role="region"
    >
      <Tab
        eventKey={0}
        title={<TabTitleText>DNS Zones</TabTitleText>}
        aria-label="DNS Zones"
      >
        <ZonesPage />
      </Tab>

      <Tab
        eventKey={1}
        title={<TabTitleText>Forwarders</TabTitleText>}
        aria-label="Forwarders"
      >
        <ForwardersPage />
      </Tab>

      <Tab
        eventKey={2}
        title={<TabTitleText>ACLs</TabTitleText>}
        aria-label="ACLs"
      >
        <AclsPage />
      </Tab>

      <Tab
        eventKey={3}
        title={<TabTitleText>TSIG Keys</TabTitleText>}
        aria-label="TSIG Keys"
      >
        <TsigKeysPage />
      </Tab>

      <Tab
        eventKey={4}
        title={<TabTitleText>Logging</TabTitleText>}
        aria-label="Logging"
      >
        <LoggingPage />
      </Tab>

      <Tab
        eventKey={5}
        title={<TabTitleText>Backups</TabTitleText>}
        aria-label="Backups"
      >
        <BackupsPage />
      </Tab>
    </Tabs>
  );
};
