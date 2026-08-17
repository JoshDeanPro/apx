import React, {useEffect, useMemo, useState} from 'react';
import {Box, Text, render, useApp, useInput} from 'ink';
import {
  ConfirmInput,
  PasswordInput,
  Spinner,
  TextInput
} from '@inkjs/ui';
import {spawn} from 'node:child_process';

const ORANGE = '#ff6a00';
const MUTED = '#777777';
const DIM = '#555555';

const PYTHON = process.env.APX_PYTHON || 'python3';

function normalizeStatus(status) {
  if (!status) {
    return null;
  }

  if (typeof status === 'object') {
    const state = String(status.state || '').toLowerCase();
    const label = String(status.label || status.state || '').trim();

    return {
      state,
      label
    };
  }

  const label = String(status).trim();
  const value = label.toLowerCase();

  if (
    value.includes('healthy') ||
    value.includes('working') ||
    value.includes('connected') ||
    value.includes('online') ||
    value.includes('active') ||
    value.includes('enabled') ||
    value.includes('assigned') ||
    value.includes('configured') ||
    value.includes('local')
  ) {
    return {state: 'healthy', label};
  }

  if (
    value.includes('sync') ||
    value.includes('starting') ||
    value.includes('connecting') ||
    value.includes('checking') ||
    value.includes('pending')
  ) {
    return {state: 'progress', label};
  }

  if (
    value.includes('need') ||
    value.includes('setup') ||
    value.includes('attention') ||
    value.includes('partial') ||
    value.includes('expired')
  ) {
    return {state: 'attention', label};
  }

  if (
    value.includes('fail') ||
    value.includes('error') ||
    value.includes('invalid') ||
    value.includes('unreachable') ||
    value.includes('denied') ||
    value.includes('authentication')
  ) {
    return {state: 'failed', label};
  }

  if (
    value.includes('disabled') ||
    value.includes('offline') ||
    value.includes('inactive') ||
    value.includes('not configured') ||
    value.includes('not assigned') ||
    value.includes('not connected') ||
    value.includes('none')
  ) {
    return {state: 'inactive', label};
  }

  return {state: 'neutral', label};
}

function StatusIndicator({status}) {
  const normalized = normalizeStatus(status);

  if (!normalized) {
    return null;
  }

  const styles = {
    healthy: {
      symbol: '●',
      color: 'green'
    },
    inactive: {
      symbol: '○',
      color: MUTED
    },
    progress: {
      symbol: '◐',
      color: ORANGE
    },
    attention: {
      symbol: '!',
      color: ORANGE
    },
    failed: {
      symbol: '×',
      color: 'red'
    },
    neutral: {
      symbol: '•',
      color: MUTED
    }
  };

  const style = styles[normalized.state] || styles.neutral;

  return (
    <>
      <Text color={style.color}>{style.symbol}</Text>
      <Text color={MUTED}> {normalized.label}</Text>
    </>
  );
}


function bridge(command, payload = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(
      PYTHON,
      ['-m', 'apx.ui_bridge', command],
      {
        env: process.env,
        stdio: ['pipe', 'pipe', 'pipe']
      }
    );

    let out = '';
    let err = '';

    child.stdout.on('data', chunk => {
      out += chunk.toString();
    });

    child.stderr.on('data', chunk => {
      err += chunk.toString();
    });

    child.on('error', reject);

    child.on('close', code => {
      let data;

      try {
        data = JSON.parse(out.trim() || '{}');
      } catch {
        reject(new Error(err.trim() || 'APX returned an unreadable response.'));
        return;
      }

      if (code !== 0 || data.ok === false) {
        reject(new Error(data.error || err.trim() || 'That action could not be completed.'));
        return;
      }

      resolve(data);
    });

    child.stdin.end(JSON.stringify(payload));
  });
}

function Header({crumb = []}) {
  const text = ['OpenPower', ...crumb].join('  ›  ');

  return (
    <Box flexDirection="column" marginBottom={1}>
      <Text color={ORANGE} bold>◆ OpenPower</Text>
      {crumb.length > 0 ? <Text color={MUTED}>{text}</Text> : null}
    </Box>
  );
}

function Footer({back = false}) {
  return (
    <Box marginTop={1}>
      <Text color={DIM}>
        ↑↓ move   enter select{back ? '   esc back' : '   q quit'}
      </Text>
    </Box>
  );
}

function Menu({
  crumb = [],
  title,
  subtitle,
  items,
  onSelect,
  onBack,
  allowQuit = false,
  onQuitRequest
}) {
  const [index, setIndex] = useState(0);
  const {exit} = useApp();

  useEffect(() => {
    setIndex(0);
  }, [title, items.length]);

  useInput((input, key) => {
    if (key.upArrow || input === 'k') {
      setIndex(value => (value > 0 ? value - 1 : Math.max(0, items.length - 1)));
      return;
    }

    if (key.downArrow || input === 'j') {
      setIndex(value => (value < items.length - 1 ? value + 1 : 0));
      return;
    }

    if (key.return || key.rightArrow) {
      if (items[index]) {
        onSelect(items[index], index);
      }
      return;
    }

    if ((key.escape || key.leftArrow) && onBack) {
      onBack();
      return;
    }

    if (key.escape && allowQuit && onQuitRequest) {
      onQuitRequest();
      return;
    }

    if (input === 'q' && allowQuit) {
      if (onQuitRequest) {
        onQuitRequest();
      } else {
        exit();
      }
    }
  });

  return (
    <Box flexDirection="column">
      <Header crumb={crumb} />

      {title ? <Text bold>{title}</Text> : null}
      {subtitle ? <Text color={MUTED}>{subtitle}</Text> : null}

      <Box flexDirection="column" marginTop={1}>
        {items.map((item, i) => {
          const selected = i === index;

          return (
            <Box key={`${item.id ?? item.label}-${i}`}>
              <Text color={selected ? ORANGE : undefined} bold={selected}>
                {selected ? '◆ ' : '  '}
                {item.label}
              </Text>

              {item.description ? (
                <Text color={MUTED}>  {item.description}</Text>
              ) : null}

              {item.status ? (
                <>
                  <Text color={MUTED}>  </Text>
                  <StatusIndicator status={item.status} />
                </>
              ) : null}
            </Box>
          );
        })}
      </Box>

      <Footer back={Boolean(onBack)} />
    </Box>
  );
}

function Loading({crumb = [], text = 'Loading…'}) {
  return (
    <Box flexDirection="column">
      <Header crumb={crumb} />
      <Spinner label={text} />
    </Box>
  );
}

function Message({crumb = [], title, message, onBack, actionLabel = 'Back'}) {
  return (
    <Menu
      crumb={crumb}
      title={title}
      subtitle={message}
      items={[{id: 'back', label: actionLabel}]}
      onSelect={onBack}
      onBack={onBack}
    />
  );
}

function ErrorScreen({crumb = [], error, onBack}) {
  return (
    <Message
      crumb={crumb}
      title="Something went wrong"
      message={error?.message || String(error)}
      onBack={onBack}
    />
  );
}

function DetailScreen({crumb, title, values, onBack}) {
  useInput((input, key) => {
    if (key.escape || key.leftArrow || key.return || input === 'q') {
      onBack();
    }
  });

  return (
    <Box flexDirection="column">
      <Header crumb={crumb} />
      <Text bold>{title}</Text>

      <Box flexDirection="column" marginTop={1}>
        {values.map(([label, value]) => (
          <Box key={label}>
            <Text color={MUTED}>{label.padEnd(18)}</Text>
            <Text>{String(value ?? '—')}</Text>
          </Box>
        ))}
      </Box>

      <Box marginTop={1}>
        <Text color={DIM}>esc back</Text>
      </Box>
    </Box>
  );
}

function Root({go}) {
  const [confirming, setConfirming] = useState(false);
  const {exit} = useApp();

  useInput((input, key) => {
    if (confirming) {
      if (input.toLowerCase() === 'y' || key.return) exit();
      if (input.toLowerCase() === 'n' || key.escape) setConfirming(false);
    }
  });

  if (confirming) {
    return (
      <Box flexDirection="column" padding={1}>
        <Text color={DIM}>┌──────────────────────────────────────────────────┐</Text>
        <Text color={DIM}>│  </Text><Text bold>Exit APX?</Text><Text color={DIM}>{'                                       │'}</Text>
        <Text color={DIM}>├──────────────────────────────────────────────────┤</Text>
        <Text color={DIM}>│  </Text><Text>Press [Y]es to Exit, or [N]o to Cancel</Text><Text color={DIM}>          │</Text>
        <Text color={DIM}>└──────────────────────────────────────────────────┘</Text>
      </Box>
    );
  }

  return (
    <Menu
      title="What would you like to manage?"
      allowQuit
      onQuitRequest={() => setConfirming(true)}
      items={[
        {id: 'devices', label: 'Devices', description: 'Machines and connections'},
        {id: 'agents', label: 'Agents', description: 'Connected actors and clients'},
        {id: 'prompts', label: 'Prompts', description: 'Portable prompts and stacks'},
        {id: 'services', label: 'Services', description: 'Domains, DNS, APIs and more'},
        {id: 'plugins', label: 'Plugins', description: 'Add and manage capabilities'},
        {id: 'settings', label: 'OpenPower Settings', description: 'Account, servers and APX'}
      ]}
      onSelect={item => go({name: item.id})}
    />
  );
}

function Devices({go, back}) {
  const [state, setState] = useState({loading: true, data: null, error: null});

  useEffect(() => {
    bridge('devices')
      .then(data => setState({loading: false, data, error: null}))
      .catch(error => setState({loading: false, data: null, error}));
  }, []);

  if (state.loading) {
    return <Loading crumb={['Devices']} text="Finding devices…" />;
  }

  if (state.error) {
    return <ErrorScreen crumb={['Devices']} error={state.error} onBack={back} />;
  }

  const items = [
    ...(state.data?.items || []).map(device => ({
      id: device.id,
      label: device.name,
      description: device.local ? 'This device' : '',
      status: device.health || device.status || (device.local ? 'Online' : 'Configured'),
      device
    })),
    {
      id: 'link',
      label: 'Link a device',
      description: 'Local or through OpenPower'
    }
  ];

  return (
    <Menu
      crumb={['Devices']}
      title="Devices"
      items={items}
      onSelect={item => {
        if (item.device) {
          go({name: 'device', device: item.device});
        } else {
          go({name: 'device-link'});
        }
      }}
      onBack={back}
    />
  );
}

function Device({screen, go, back}) {
  const device = screen.device;

  return (
    <Menu
      crumb={['Devices', device.name]}
      title={device.name}
      subtitle={device.local ? 'This device' : device.status}
      items={[
        {id: 'details', label: 'Details', description: 'System and APX information'},
        {id: 'nickname', label: 'Nickname', description: device.nickname || 'Use a friendly name'},
        {id: 'services', label: 'Services', description: 'Assign services to this device'},
        {id: 'server-mode', label: 'Server Mode', description: 'Configure this device as an APX Server'},
        {id: 'shared', label: 'Shared Settings', description: 'Portable settings and prompts'},
        {id: 'connections', label: 'Connections', description: 'How this device is linked'},
        {id: 'settings', label: 'Settings', description: 'Device-specific configuration'}
      ]}
      onSelect={item => {
        if (item.id === 'details') {
          go({name: 'device-details', device});
        } else if (item.id === 'nickname') {
          go({name: 'device-nickname', device});
        } else if (item.id === 'services') {
          go({name: 'device-services', device});
        } else if (item.id === 'server-mode') {
          go({name: 'device-server-mode', device});
        } else if (item.id === 'shared') {
          go({name: 'shared-settings', device});
        } else {
          go({
            name: 'simple-message',
            crumb: ['Devices', device.name, item.label],
            title: item.label,
            message: 'This area is ready for capability-provided settings.'
          });
        }
      }}
      onBack={back}
    />
  );
}

function DeviceServerMode({screen, go, back}) {
  const device = screen.device;
  const isServer = device.server_enabled || false;

  return (
    <Menu
      crumb={['Devices', device.name, 'Server Mode']}
      title="Server Configuration"
      subtitle={isServer ? 'Active' : 'Disabled'}
      items={[
        {id: 'toggle', label: isServer ? 'Disable Server' : 'Enable Server', description: 'Control APX server listeners'},
        ...(isServer ? [
          {id: 'listeners', label: 'Listeners', description: 'Port and protocol configuration'},
          {id: 'capabilities', label: 'Capabilities', description: 'Exposed actions and scope'},
          {id: 'clients', label: 'Connected Clients', description: 'View and manage active connections'},
          {id: 'permissions', label: 'Client Permissions', description: 'Global and client-specific policies'},
          {id: 'health', label: 'Server Health', description: 'Status and diagnostics'},
          {id: 'logs', label: 'Logs', description: 'Safe local log viewer'}
        ] : [])
      ]}
      onSelect={item => {
        go({
          name: 'simple-message',
          crumb: ['Devices', device.name, 'Server Mode', item.label],
          title: item.label,
          message: 'Backend API implementation required to support this configuration.'
        });
      }}
      onBack={back}
    />
  );
}

function DeviceDetails({screen, back}) {
  const d = screen.device;

  return (
    <DetailScreen
      crumb={['Devices', d.name, 'Details']}
      title="About this device"
      values={[
        ['Nickname', d.nickname || 'None'],
        ['System name', d.system_name],
        ['Status', d.status],
        ['Operating system', [d.os, d.os_version].filter(Boolean).join(' ')],
        ['Architecture', d.architecture],
        ['Processor', d.processor],
        ['Memory', d.memory_gb ? `${d.memory_gb} GB` : '—'],
        ['Storage free', d.storage_free_gb ? `${d.storage_free_gb} GB` : '—'],
        ['APX', d.apx_version],
        ['Protocol', d.protocol_version],
        ['LocalCloud', d.localcloud]
      ]}
      onBack={back}
    />
  );
}

function NicknameEditor({screen, back}) {
  const device = screen.device;
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  if (saving) {
    return <Loading crumb={['Devices', device.name, 'Nickname']} text="Saving…" />;
  }

  if (error) {
    return <ErrorScreen crumb={['Devices', device.name, 'Nickname']} error={error} onBack={back} />;
  }

  return (
    <Box flexDirection="column">
      <Header crumb={['Devices', device.name, 'Nickname']} />
      <Text>Choose a friendly name.</Text>
      <Text color={MUTED}>The real system name stays {device.system_name}.</Text>

      <Box marginTop={1}>
        <Text color={ORANGE}>◆ </Text>
        <TextInput
          placeholder={device.nickname || device.name}
          onSubmit={async value => {
            setSaving(true);

            try {
              await bridge('nickname-set', {
                device: device.system_name,
                value
              });
              back(true);
            } catch (e) {
              setSaving(false);
              setError(e);
            }
          }}
        />
      </Box>
    </Box>
  );
}

function DeviceServices({screen, back}) {
  const device = screen.device;
  const [state, setState] = useState({loading: true, services: [], management: null, error: null});

  const load = async () => {
    try {
      const [serviceData, management] = await Promise.all([
        bridge('services'),
        bridge('state')
      ]);

      setState({
        loading: false,
        services: serviceData.items || [],
        management: management.state,
        error: null
      });
    } catch (error) {
      setState({loading: false, services: [], management: null, error});
    }
  };

  useEffect(() => {
    load();
  }, []);

  if (state.loading) {
    return <Loading crumb={['Devices', device.name, 'Services']} />;
  }

  if (state.error) {
    return <ErrorScreen crumb={['Devices', device.name, 'Services']} error={state.error} onBack={back} />;
  }

  const items = state.services.map(service => {
    const assigned = (state.management?.assignments?.[service.id] || []).includes(device.id);

    return {
      id: service.id,
      label: service.name,
      description: '',
      status: assigned ? 'Assigned' : 'Not assigned',
      service,
      assigned
    };
  });

  if (!items.length) {
    return (
      <Message
        crumb={['Devices', device.name, 'Services']}
        title="No services available yet"
        message="Install or configure a service first."
        onBack={back}
      />
    );
  }

  return (
    <Menu
      crumb={['Devices', device.name, 'Services']}
      title="Choose services for this device"
      items={items}
      onSelect={async item => {
        await bridge('assignment-toggle', {
          service: item.service.id,
          device: device.id
        });

        await load();
      }}
      onBack={back}
    />
  );
}

function Services({go, back}) {
  const [state, setState] = useState({loading: true, data: null, error: null});

  useEffect(() => {
    bridge('services')
      .then(data => setState({loading: false, data, error: null}))
      .catch(error => setState({loading: false, data: null, error}));
  }, []);

  if (state.loading) {
    return <Loading crumb={['Services']} text="Finding services…" />;
  }

  if (state.error) {
    return <ErrorScreen crumb={['Services']} error={state.error} onBack={back} />;
  }

  const services = state.data?.items || [];

  if (!services.length) {
    return (
      <Menu
        crumb={['Services']}
        title="No services connected yet"
        items={[
          {
            id: 'plugins',
            label: 'Find a plugin',
            description: 'Add a service capability'
          }
        ]}
        onSelect={() => go({name: 'plugins'})}
        onBack={back}
      />
    );
  }

  return (
    <Menu
      crumb={['Services']}
      title="Services"
      items={services.map(service => ({
        id: service.id,
        label: service.name,
        description: service.description || '',
        status: service.health || service.status || 'Available',
        service
      }))}
      onSelect={item => go({name: 'service', service: item.service})}
      onBack={back}
    />
  );
}

function Service({screen, go, back}) {
  const service = screen.service;
  const porkbun = service.id.toLowerCase().includes('porkbun');

  const items = [];

  if (porkbun) {
    items.push({
      id: 'domains',
      label: 'Domains',
      description: 'Manage domains and DNS'
    });
  }

  items.push(
    {
      id: 'credentials',
      label: 'Credentials',
      description: 'Add, replace, test or remove keys'
    },
    {
      id: 'connections',
      label: 'Connections',
      description: 'Connect this service to another capability'
    },
    {
      id: 'assignments',
      label: 'Assignments',
      description: 'Choose devices that can use this service'
    },
    {
      id: 'settings',
      label: 'Settings',
      description: 'Portable and service-specific behavior'
    },
    {
      id: 'toggle',
      label: 'Enable / Disable',
      description: 'Control whether this service is available'
    },
    {
      id: 'about',
      label: 'About',
      description: 'Version and capability details'
    }
  );

  return (
    <Menu
      crumb={['Services', service.name]}
      title={service.name}
      subtitle={service.description || ''}
      items={[
        {
          id: '__status',
          label: 'Status',
          status: service.health || service.status || 'Available',
          description: ''
        },
        ...items
      ]}
      onSelect={item => {
        if (item.id === '__status') {
          go({
            name: 'service-health',
            service
          });
        } else if (item.id === 'domains') {
          go({name: 'porkbun-domains', service});
        } else if (item.id === 'credentials') {
          go({name: 'credentials', service});
        } else if (item.id === 'connections') {
          go({name: 'service-connections', service});
        } else if (item.id === 'assignments') {
          go({name: 'service-assignments', service});
        } else if (item.id === 'settings') {
          go({name: 'service-settings', service});
        } else if (item.id === 'toggle') {
          go({name: 'service-toggle', service});
        } else if (item.id === 'about') {
          go({name: 'service-about', service});
        }
      }}
      onBack={back}
    />
  );
}

function Credentials({screen, go, back}) {
  const service = screen.service;
  const [state, setState] = useState({loading: true, data: null, error: null});

  const load = () => {
    setState(s => ({...s, loading: true}));

    bridge('credential-status', {service: service.id})
      .then(data => setState({loading: false, data, error: null}))
      .catch(error => setState({loading: false, data: null, error}));
  };

  useEffect(load, [service.id]);

  if (state.loading) {
    return <Loading crumb={['Services', service.name, 'Credentials']} />;
  }

  if (state.error) {
    return <ErrorScreen crumb={['Services', service.name, 'Credentials']} error={state.error} onBack={back} />;
  }

  const fields = state.data?.fields || [];

  const items = fields.map(field => ({
    id: field.id,
    label: field.label,
    description: '',
    status: field.configured ? 'Configured' : 'Needs setup',
    field
  }));

  items.push({
    id: 'test',
    label: 'Test credentials',
    description: 'Verify that the service accepts them'
  });

  for (const field of fields.filter(x => x.configured)) {
    items.push({
      id: `remove:${field.id}`,
      label: `Remove ${field.label}`,
      field,
      remove: true
    });
  }

  return (
    <Menu
      crumb={['Services', service.name, 'Credentials']}
      title="Credentials"
      subtitle="Secret values stay in the system credential store."
      items={items}
      onSelect={item => {
        if (item.id === 'test') {
          go({name: 'credential-test', service});
        } else if (item.remove) {
          go({name: 'credential-remove', service, field: item.field});
        } else {
          go({name: 'credential-edit', service, field: item.field});
        }
      }}
      onBack={back}
    />
  );
}

function CredentialEditor({screen, back}) {
  const {service, field} = screen;
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  if (saving) {
    return <Loading crumb={['Services', service.name, 'Credentials', field.label]} text="Saving securely…" />;
  }

  if (error) {
    return <ErrorScreen crumb={['Services', service.name, 'Credentials']} error={error} onBack={back} />;
  }

  return (
    <Box flexDirection="column">
      <Header crumb={['Services', service.name, 'Credentials', field.label]} />

      <Text>{field.label}</Text>
      <Text color={MUTED}>The value will be masked and stored securely.</Text>

      <Box marginTop={1}>
        <Text color={ORANGE}>◆ </Text>
        <PasswordInput
          placeholder={`Enter ${field.label}`}
          onSubmit={async value => {
            setSaving(true);

            try {
              await bridge('credential-set', {
                service: service.id,
                field: field.id,
                value
              });

              back(true);
            } catch (e) {
              setSaving(false);
              setError(e);
            }
          }}
        />
      </Box>
    </Box>
  );
}

function CredentialTest({screen, back}) {
  const {service} = screen;
  const [state, setState] = useState({loading: true, message: null, error: null});

  useEffect(() => {
    bridge('service-test', {service: service.id})
      .then(data => setState({loading: false, message: data.message, error: null}))
      .catch(error => setState({loading: false, message: null, error}));
  }, [service.id]);

  if (state.loading) {
    return <Loading crumb={['Services', service.name, 'Credentials']} text="Testing credentials…" />;
  }

  if (state.error) {
    return <ErrorScreen crumb={['Services', service.name, 'Credentials']} error={state.error} onBack={back} />;
  }

  return (
    <Message
      crumb={['Services', service.name, 'Credentials']}
      title="Connected"
      message={state.message}
      onBack={back}
    />
  );
}

function CredentialRemove({screen, back}) {
  const {service, field} = screen;
  const [working, setWorking] = useState(false);
  const [error, setError] = useState(null);

  if (working) {
    return <Loading crumb={['Services', service.name, 'Credentials']} text="Removing credential…" />;
  }

  if (error) {
    return <ErrorScreen crumb={['Services', service.name, 'Credentials']} error={error} onBack={back} />;
  }

  return (
    <Box flexDirection="column">
      <Header crumb={['Services', service.name, 'Credentials']} />
      <Text>Remove {field.label}?</Text>

      <Box marginTop={1}>
        <ConfirmInput
          onConfirm={async () => {
            setWorking(true);

            try {
              await bridge('credential-delete', {
                service: service.id,
                field: field.id
              });

              back(true);
            } catch (e) {
              setWorking(false);
              setError(e);
            }
          }}
          onCancel={back}
        />
      </Box>
    </Box>
  );
}

function PorkbunDomains({screen, go, back}) {
  const service = screen.service;
  const [state, setState] = useState({loading: true, items: [], error: null});

  useEffect(() => {
    bridge('porkbun-domains')
      .then(data => setState({loading: false, items: data.items || [], error: null}))
      .catch(error => setState({loading: false, items: [], error}));
  }, []);

  if (state.loading) {
    return <Loading crumb={['Services', service.name, 'Domains']} text="Loading domains…" />;
  }

  if (state.error) {
    return <ErrorScreen crumb={['Services', service.name, 'Domains']} error={state.error} onBack={back} />;
  }

  if (!state.items.length) {
    return (
      <Message
        crumb={['Services', service.name, 'Domains']}
        title="No domains found"
        message="The connected Porkbun account returned no domains."
        onBack={back}
      />
    );
  }

  return (
    <Menu
      crumb={['Services', service.name, 'Domains']}
      title="Domains"
      items={state.items.map(item => {
        const domain = item.domain || item.name;

        return {
          id: domain,
          label: domain,
          description: item.expireDate ? `Expires ${item.expireDate}` : '',
          domain,
          data: item
        };
      })}
      onSelect={item => go({
        name: 'porkbun-domain',
        service,
        domain: item.domain,
        data: item.data
      })}
      onBack={back}
    />
  );
}

function PorkbunDomain({screen, go, back}) {
  return (
    <Menu
      crumb={['Services', screen.service.name, 'Domains', screen.domain]}
      title={screen.domain}
      items={[
        {
          id: 'dns',
          label: 'DNS Records',
          description: 'View, add and remove records'
        },
        {
          id: 'details',
          label: 'Details',
          description: 'Registration information'
        }
      ]}
      onSelect={item => {
        if (item.id === 'dns') {
          go({
            name: 'porkbun-dns',
            service: screen.service,
            domain: screen.domain
          });
        } else {
          go({
            name: 'domain-details',
            service: screen.service,
            domain: screen.domain,
            data: screen.data
          });
        }
      }}
      onBack={back}
    />
  );
}

function PorkbunDNS({screen, go, back}) {
  const [state, setState] = useState({loading: true, items: [], error: null});

  const load = () => {
    setState({loading: true, items: [], error: null});

    bridge('porkbun-dns', {domain: screen.domain})
      .then(data => setState({loading: false, items: data.items || [], error: null}))
      .catch(error => setState({loading: false, items: [], error}));
  };

  useEffect(load, [screen.domain]);

  if (state.loading) {
    return <Loading crumb={['Services', screen.service.name, 'Domains', screen.domain, 'DNS']} />;
  }

  if (state.error) {
    return <ErrorScreen crumb={['Services', screen.service.name, 'DNS']} error={state.error} onBack={back} />;
  }

  const items = [
    {
      id: 'add',
      label: 'Add DNS record',
      description: 'Validated before it is applied'
    },
    ...state.items.map(record => ({
      id: String(record.id),
      label: `${record.type || '?'}  ${record.name || '@'}`,
      description: record.content || '',
      record
    }))
  ];

  return (
    <Menu
      crumb={['Services', screen.service.name, 'Domains', screen.domain, 'DNS']}
      title="DNS Records"
      items={items}
      onSelect={item => {
        if (item.id === 'add') {
          go({
            name: 'porkbun-dns-add',
            service: screen.service,
            domain: screen.domain
          });
        } else {
          go({
            name: 'porkbun-dns-record',
            service: screen.service,
            domain: screen.domain,
            record: item.record
          });
        }
      }}
      onBack={back}
    />
  );
}

function DNSAdd({screen, back}) {
  const [step, setStep] = useState('type');
  const [form, setForm] = useState({
    type: 'A',
    name: '',
    content: '',
    ttl: '600'
  });
  const [working, setWorking] = useState(false);
  const [error, setError] = useState(null);

  if (working) {
    return <Loading crumb={['Services', screen.service.name, screen.domain, 'Add DNS']} text="Validating and creating record…" />;
  }

  if (error) {
    return <ErrorScreen crumb={['Services', screen.service.name, screen.domain, 'Add DNS']} error={error} onBack={back} />;
  }

  const labels = {
    type: 'Record type',
    name: 'Name / host',
    content: 'Value',
    ttl: 'TTL'
  };

  const placeholders = {
    type: 'A',
    name: '@',
    content: '1.2.3.4',
    ttl: '600'
  };

  const submit = async value => {
    const next = {
      ...form,
      [step]: value || form[step]
    };

    setForm(next);

    if (step === 'type') {
      setStep('name');
    } else if (step === 'name') {
      setStep('content');
    } else if (step === 'content') {
      setStep('ttl');
    } else {
      setWorking(true);

      try {
        await bridge('porkbun-dns-create', {
          domain: screen.domain,
          ...next,
          ttl: value || next.ttl
        });

        back(true);
      } catch (e) {
        setWorking(false);
        setError(e);
      }
    }
  };

  return (
    <Box flexDirection="column">
      <Header crumb={['Services', screen.service.name, 'Domains', screen.domain, 'Add DNS']} />

      <Text>{labels[step]}</Text>

      {step === 'name' ? (
        <Text color={MUTED}>Use @ or leave blank for the root domain.</Text>
      ) : null}

      <Box marginTop={1}>
        <Text color={ORANGE}>◆ </Text>
        <TextInput
          placeholder={placeholders[step]}
          onSubmit={submit}
        />
      </Box>
    </Box>
  );
}

function DNSRecord({screen, go, back}) {
  const r = screen.record;

  return (
    <Menu
      crumb={['Services', screen.service.name, 'Domains', screen.domain, 'DNS']}
      title={`${r.type || 'Record'} ${r.name || '@'}`}
      subtitle={r.content || ''}
      items={[
        {
          id: 'delete',
          label: 'Delete record',
          description: 'APX validates the deletion first'
        },
        {
          id: 'details',
          label: 'Details',
          description: `TTL ${r.ttl || '—'}`
        }
      ]}
      onSelect={item => {
        if (item.id === 'delete') {
          go({...screen, name: 'porkbun-dns-delete'});
        } else {
          go({
            name: 'record-details',
            record: r,
            service: screen.service,
            domain: screen.domain
          });
        }
      }}
      onBack={back}
    />
  );
}

function DNSDelete({screen, back}) {
  const [working, setWorking] = useState(false);
  const [error, setError] = useState(null);

  if (working) {
    return <Loading crumb={['Services', screen.service.name, screen.domain, 'DNS']} text="Validating and deleting…" />;
  }

  if (error) {
    return <ErrorScreen crumb={['Services', screen.service.name, 'DNS']} error={error} onBack={back} />;
  }

  return (
    <Box flexDirection="column">
      <Header crumb={['Services', screen.service.name, 'Domains', screen.domain, 'DNS']} />

      <Text>Delete {screen.record.type} {screen.record.name || '@'}?</Text>
      <Text color={MUTED}>{screen.record.content}</Text>

      <Box marginTop={1}>
        <ConfirmInput
          onConfirm={async () => {
            setWorking(true);

            try {
              await bridge('porkbun-dns-delete', {
                domain: screen.domain,
                id: screen.record.id
              });

              back(true);
            } catch (e) {
              setWorking(false);
              setError(e);
            }
          }}
          onCancel={back}
        />
      </Box>
    </Box>
  );
}

function ServiceAssignments({screen, back}) {
  const service = screen.service;
  const [state, setState] = useState({loading: true, devices: [], management: null, error: null});

  const load = async () => {
    try {
      const [deviceData, management] = await Promise.all([
        bridge('devices'),
        bridge('state')
      ]);

      setState({
        loading: false,
        devices: deviceData.items || [],
        management: management.state,
        error: null
      });
    } catch (error) {
      setState({loading: false, devices: [], management: null, error});
    }
  };

  useEffect(() => {
    load();
  }, []);

  if (state.loading) {
    return <Loading crumb={['Services', service.name, 'Assignments']} />;
  }

  if (state.error) {
    return <ErrorScreen crumb={['Services', service.name, 'Assignments']} error={state.error} onBack={back} />;
  }

  return (
    <Menu
      crumb={['Services', service.name, 'Assignments']}
      title="Where can this service be used?"
      items={state.devices.map(device => {
        const assigned = (state.management?.assignments?.[service.id] || []).includes(device.id);

        return {
          id: device.id,
          label: device.name,
          description: '',
          status: assigned ? 'Assigned' : 'Not assigned',
          device
        };
      })}
      onSelect={async item => {
        await bridge('assignment-toggle', {
          service: service.id,
          device: item.device.id
        });

        await load();
      }}
      onBack={back}
    />
  );
}

function ServiceConnections({screen, back}) {
  const service = screen.service;
  const [state, setState] = useState({loading: true, services: [], management: null, error: null});

  const load = async () => {
    try {
      const [serviceData, management] = await Promise.all([
        bridge('services'),
        bridge('state')
      ]);

      setState({
        loading: false,
        services: (serviceData.items || []).filter(x => x.id !== service.id),
        management: management.state,
        error: null
      });
    } catch (error) {
      setState({loading: false, services: [], management: null, error});
    }
  };

  useEffect(() => {
    load();
  }, []);

  if (state.loading) {
    return <Loading crumb={['Services', service.name, 'Connections']} />;
  }

  if (state.error) {
    return <ErrorScreen crumb={['Services', service.name, 'Connections']} error={state.error} onBack={back} />;
  }

  return (
    <Menu
      crumb={['Services', service.name, 'Connections']}
      title="Connect services"
      subtitle="Connections make capabilities portable across workflows."
      items={state.services.map(target => {
        const connected = (state.management?.connections || []).some(
          x => x.source === service.id && x.target === target.id
        );

        return {
          id: target.id,
          label: target.name,
          description: '',
          status: connected ? 'Connected' : 'Not connected',
          target,
          connected
        };
      })}
      onSelect={async item => {
        await bridge(
          item.connected ? 'connection-remove' : 'connection-add',
          {
            source: service.id,
            target: item.target.id
          }
        );

        await load();
      }}
      onBack={back}
    />
  );
}

function ServiceToggle({screen, back}) {
  const [working, setWorking] = useState(true);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    bridge('service-toggle', {service: screen.service.id})
      .then(data => {
        setResult(data);
        setWorking(false);
      })
      .catch(e => {
        setError(e);
        setWorking(false);
      });
  }, []);

  if (working) {
    return <Loading crumb={['Services', screen.service.name]} text="Updating service…" />;
  }

  if (error) {
    return <ErrorScreen crumb={['Services', screen.service.name]} error={error} onBack={back} />;
  }

  return (
    <Message
      crumb={['Services', screen.service.name]}
      title={result.enabled ? 'Service enabled' : 'Service disabled'}
      message={result.enabled ? 'This service can now be used.' : 'This service is no longer available to assignments.'}
      onBack={back}
    />
  );
}

function ServiceSettings({screen, go, back}) {
  return (
    <Menu
      crumb={['Services', screen.service.name, 'Settings']}
      title="Service behavior"
      items={[
        {
          id: 'best',
          label: 'Best Practice',
          description: 'Allow capable clients to choose safe recommended settings'
        },
        {
          id: 'custom',
          label: 'Custom',
          description: 'Use portable settings you control'
        },
        {
          id: 'manual',
          label: 'Manual',
          description: 'Require explicit choices'
        }
      ]}
      onSelect={async item => {
        const map = {
          best: 'best-practice',
          custom: 'custom',
          manual: 'manual'
        };

        await bridge('shared-mode', {mode: map[item.id]});

        go({
          name: 'simple-message',
          crumb: ['Services', screen.service.name, 'Settings'],
          title: 'Settings saved',
          message: `${item.label} is now the active behavior.`
        });
      }}
      onBack={back}
    />
  );
}

function Plugins({go, back}) {
  const [state, setState] = useState({loading: true, items: [], error: null});

  useEffect(() => {
    bridge('plugins')
      .then(data => setState({loading: false, items: data.items || [], error: null}))
      .catch(error => setState({loading: false, items: [], error}));
  }, []);

  if (state.loading) {
    return <Loading crumb={['Plugins']} text="Finding plugins…" />;
  }

  if (state.error) {
    return <ErrorScreen crumb={['Plugins']} error={state.error} onBack={back} />;
  }

  const items = [
    {
      id: 'search',
      label: 'Search',
      description: 'Find additional capabilities'
    },
    ...state.items.map(plugin => ({
      id: plugin.id,
      label: plugin.name,
      description: plugin.description || '',
      status: plugin.status || 'Installed',
      plugin
    }))
  ];

  return (
    <Menu
      crumb={['Plugins']}
      title="Plugins"
      items={items}
      onSelect={item => {
        if (item.id === 'search') {
          go({
            name: 'simple-message',
            crumb: ['Plugins', 'Search'],
            title: 'Plugin search',
            message: 'Search can be connected to the OpenPower plugin registry when the registry endpoint is enabled.'
          });
        } else {
          go({name: 'plugin', plugin: item.plugin});
        }
      }}
      onBack={back}
    />
  );
}

function Plugin({screen, go, back}) {
  const p = screen.plugin;

  return (
    <Menu
      crumb={['Plugins', p.name]}
      title={p.name}
      subtitle={p.description || p.status}
      items={[
        {id: 'service', label: 'Manage Service', description: 'Open its management interface'},
        {id: 'toggle', label: 'Enable / Disable', description: 'Control availability'},
        {id: 'about', label: 'About', description: 'Version and contributed capabilities'}
      ]}
      onSelect={item => {
        if (item.id === 'service') {
          go({
            name: 'service',
            service: {
              id: p.id,
              name: p.name,
              description: p.description,
              status: p.status,
              raw: p.raw
            }
          });
        } else if (item.id === 'toggle') {
          go({
            name: 'service-toggle',
            service: {id: p.id, name: p.name}
          });
        } else {
          go({
            name: 'plugin-about',
            plugin: p
          });
        }
      }}
      onBack={back}
    />
  );
}

function Prompts({go, back}) {
  const [state, setState] = useState({loading: true, prompts: [], error: null});

  const load = () => {
    bridge('state')
      .then(data => setState({
        loading: false,
        prompts: data.state.prompts || [],
        error: null
      }))
      .catch(error => setState({loading: false, prompts: [], error}));
  };

  useEffect(load, []);

  if (state.loading) {
    return <Loading crumb={['Prompts']} />;
  }

  if (state.error) {
    return <ErrorScreen crumb={['Prompts']} error={state.error} onBack={back} />;
  }

  return (
    <Menu
      crumb={['Prompts']}
      title="Prompts"
      items={[
        {id: 'new', label: 'New prompt', description: 'Create a portable prompt'},
        ...state.prompts.map(prompt => ({
          id: prompt.id,
          label: prompt.name,
          description: prompt.content.slice(0, 50),
          prompt
        }))
      ]}
      onSelect={item => {
        if (item.id === 'new') {
          go({name: 'prompt-new'});
        } else {
          go({name: 'prompt', prompt: item.prompt});
        }
      }}
      onBack={back}
    />
  );
}

function NewPrompt({back}) {
  const [step, setStep] = useState('name');
  const [name, setName] = useState('');
  const [working, setWorking] = useState(false);
  const [error, setError] = useState(null);

  if (working) {
    return <Loading crumb={['Prompts', 'New']} text="Saving prompt…" />;
  }

  if (error) {
    return <ErrorScreen crumb={['Prompts', 'New']} error={error} onBack={back} />;
  }

  return (
    <Box flexDirection="column">
      <Header crumb={['Prompts', 'New']} />

      <Text>{step === 'name' ? 'Prompt name' : 'Prompt'}</Text>

      <Box marginTop={1}>
        <Text color={ORANGE}>◆ </Text>
        <TextInput
          placeholder={step === 'name' ? 'Deploy website' : 'Describe the reusable instruction…'}
          onSubmit={async value => {
            if (step === 'name') {
              setName(value);
              setStep('content');
              return;
            }

            setWorking(true);

            try {
              await bridge('prompt-add', {
                name,
                content: value
              });

              back(true);
            } catch (e) {
              setWorking(false);
              setError(e);
            }
          }}
        />
      </Box>
    </Box>
  );
}

function PromptScreen({screen, back}) {
  const [deleting, setDeleting] = useState(false);

  if (deleting) {
    return (
      <Box flexDirection="column">
        <Header crumb={['Prompts', screen.prompt.name]} />
        <Text>Delete this prompt?</Text>

        <Box marginTop={1}>
          <ConfirmInput
            onConfirm={async () => {
              await bridge('prompt-delete', {id: screen.prompt.id});
              back(true);
            }}
            onCancel={() => setDeleting(false)}
          />
        </Box>
      </Box>
    );
  }

  return (
    <Menu
      crumb={['Prompts', screen.prompt.name]}
      title={screen.prompt.name}
      subtitle={screen.prompt.content}
      items={[
        {id: 'delete', label: 'Delete prompt'}
      ]}
      onSelect={() => setDeleting(true)}
      onBack={back}
    />
  );
}

function Agents({back}) {
  const [state, setState] = useState({loading: true, items: [], error: null});

  useEffect(() => {
    bridge('agents')
      .then(data => setState({loading: false, items: data.items || [], error: null}))
      .catch(error => setState({loading: false, items: [], error}));
  }, []);

  if (state.loading) {
    return <Loading crumb={['Agents']} />;
  }

  if (state.error) {
    return <ErrorScreen crumb={['Agents']} error={state.error} onBack={back} />;
  }

  return (
    <Menu
      crumb={['Agents']}
      title="Agents and clients"
      items={state.items.map(agent => ({
        id: agent.id,
        label: agent.name,
        description: '',
        status: agent.status
      }))}
      onSelect={() => {}}
      onBack={back}
    />
  );
}

function SharedSettings({back}) {
  const [state, setState] = useState({loading: true, mode: null, error: null});

  useEffect(() => {
    bridge('state')
      .then(data => setState({
        loading: false,
        mode: data.state.shared.automation_mode,
        error: null
      }))
      .catch(error => setState({loading: false, mode: null, error}));
  }, []);

  if (state.loading) {
    return <Loading crumb={['Shared Settings']} />;
  }

  if (state.error) {
    return <ErrorScreen crumb={['Shared Settings']} error={state.error} onBack={back} />;
  }

  const modes = [
    ['best-practice', 'Best Practice', 'Capable clients may choose recommended settings'],
    ['custom', 'Custom', 'Use your portable shared configuration'],
    ['manual', 'Manual', 'Require explicit choices']
  ];

  return (
    <Menu
      crumb={['Shared Settings']}
      title="Shared behavior"
      subtitle={`Current: ${state.mode}`}
      items={modes.map(([id, label, description]) => ({
        id,
        label,
        description
      }))}
      onSelect={async item => {
        await bridge('shared-mode', {mode: item.id});
        setState(s => ({...s, mode: item.id}));
      }}
      onBack={back}
    />
  );
}

function OpenPowerSettings({go, back}) {
  return (
    <Menu
      crumb={['OpenPower Settings']}
      title="OpenPower Settings"
      items={[
        {id: 'account', label: 'Link Account', description: 'Connect OpenPower.dev'},
        {id: 'shared', label: 'Shared Settings', description: 'Portable behavior across devices'},
        {id: 'servers', label: 'APX Servers', description: 'Manage connected remote APX servers'},
        {id: 'update', label: 'Update APX', description: 'Check for a safe release'},
        {id: 'docs', label: 'Documentation', description: 'Open the APX documentation'}
      ]}
      onSelect={async item => {
        if (item.id === 'account') {
          await bridge('open', {url: 'https://openpower.dev/sign-in'});
        } else if (item.id === 'docs') {
          await bridge('open', {url: 'https://openpower.dev/apx'});
        } else if (item.id === 'shared') {
          go({name: 'shared-settings'});
        } else if (item.id === 'servers') {
          go({name: 'apx-servers'});
        } else if (item.id === 'update') {
          go({name: 'update', explicit: true});
        }
      }}
      onBack={back}
    />
  );
}

function APXServers({go, back}) {
  const [state, setState] = useState({loading: true, data: null, error: null});

  useEffect(() => {
    // Reusing the devices bridge endpoint since connected servers are represented as remote devices
    bridge('devices')
      .then(data => {
        const servers = (data?.items || []).filter(d => !d.local && d.is_apx_server);
        setState({loading: false, data: {items: servers}, error: null});
      })
      .catch(error => setState({loading: false, data: null, error}));
  }, []);

  if (state.loading) {
    return <Loading crumb={['Settings', 'APX Servers']} text="Loading servers…" />;
  }

  if (state.error) {
    return <ErrorScreen crumb={['Settings', 'APX Servers']} error={state.error} onBack={back} />;
  }

  const items = [
    ...(state.data?.items || []).map(server => ({
      id: server.id,
      label: server.name,
      description: server.status || 'Connected',
      server
    })),
    {
      id: 'connect',
      label: 'Connect to Server',
      description: 'Add a new remote APX server'
    }
  ];

  return (
    <Menu
      crumb={['Settings', 'APX Servers']}
      title="Connected APX Servers"
      items={items}
      onSelect={item => {
        if (item.id === 'connect') {
          go({name: 'simple-message', crumb: ['Settings', 'APX Servers', 'Connect'], title: 'Connect to Server', message: 'Backend integration required.'});
        } else {
          go({name: 'apx-server', server: item.server});
        }
      }}
      onBack={back}
    />
  );
}

function APXServer({screen, go, back}) {
  const server = screen.server;
  return (
    <Menu
      crumb={['Settings', 'APX Servers', server.name]}
      title={server.name}
      subtitle={server.status || 'Connected'}
      items={[
        {id: 'status', label: 'Connection Status', description: 'View current connectivity'},
        {id: 'configure', label: 'Configure', description: 'Server-specific settings'},
        {id: 'permissions', label: 'Permissions', description: 'Manage allowed actions and scope'},
        {id: 'agents', label: 'Agents', description: 'Allowed agents'},
        {id: 'devices', label: 'Devices', description: 'Allowed devices'},
        {id: 'protocol', label: 'Protocol & Version', description: 'Inspect version policies'},
        {id: 'rotate', label: 'Rotate Credentials', description: 'Rotate access tokens'},
        {id: 'revoke', label: 'Disconnect & Revoke', description: 'Terminate connection'}
      ]}
      onSelect={item => {
        go({
          name: 'simple-message',
          crumb: ['Settings', 'APX Servers', server.name, item.label],
          title: item.label,
          message: 'Backend operation to be implemented.'
        });
      }}
      onBack={back}
    />
  );
}

function UpdateScreen({explicit = false, initial = null, onContinue}) {
  const {exit} = useApp();
  const [state, setState] = useState({
    checking: !initial,
    check: initial,
    installing: false,
    result: null,
    error: null
  });

  useEffect(() => {
    if (initial) {
      return;
    }

    bridge('update-check')
      .then(check => setState(s => ({...s, checking: false, check})))
      .catch(error => setState(s => ({...s, checking: false, error})));
  }, []);

  if (state.checking) {
    return <Loading crumb={explicit ? ['Update'] : []} text="Checking APX…" />;
  }

  if (state.installing) {
    return <Loading crumb={['Update']} text="Installing and verifying update…" />;
  }

  if (state.error) {
    return (
      <ErrorScreen
        crumb={['Update']}
        error={state.error}
        onBack={onContinue || exit}
      />
    );
  }

  if (state.result) {
    return (
      <Menu
        crumb={['Update']}
        title={state.result.updated ? `APX ${state.result.version} is ready` : 'APX is up to date'}
        subtitle={state.result.updated ? 'The previous version was kept as a rollback.' : undefined}
        items={[
          {id: 'done', label: state.result.updated ? 'Restart APX' : 'Continue'}
        ]}
        onSelect={() => exit()}
      />
    );
  }

  const check = state.check || {};

  if (!check.available && !check.mandatory) {
    if (!explicit) {
      onContinue?.();
      return null;
    }

    return (
      <Message
        crumb={['Update']}
        title="APX is up to date"
        message={`Version ${check.current}`}
        onBack={onContinue || exit}
        actionLabel="Continue"
      />
    );
  }

  const items = [
    {
      id: 'update',
      label: 'Update now',
      description: `${check.current}  →  ${check.latest}`
    }
  ];

  if (!check.mandatory) {
    items.push({
      id: 'later',
      label: 'Later'
    });
  } else {
    items.push({
      id: 'exit',
      label: 'Exit APX'
    });
  }

  return (
    <Menu
      crumb={['Update']}
      title={check.mandatory ? 'APX needs an update' : `APX ${check.latest} is available`}
      subtitle={check.mandatory ? 'Your installed version is no longer supported.' : 'Would you like to update?'}
      items={items}
      onSelect={async item => {
        if (item.id === 'later') {
          onContinue?.();
          return;
        }

        if (item.id === 'exit') {
          exit();
          return;
        }

        setState(s => ({...s, installing: true}));

        try {
          const result = await bridge('update-install', {
            source_url: check.source_url
          });

          setState(s => ({
            ...s,
            installing: false,
            result
          }));
        } catch (error) {
          setState(s => ({
            ...s,
            installing: false,
            error
          }));
        }
      }}
      onBack={check.mandatory ? undefined : onContinue}
    />
  );
}

function App() {
  const argv = process.argv.slice(2);
  const explicitUpdate = argv[0] === 'update';
  const [stack, setStack] = useState([{name: explicitUpdate ? 'update' : 'gate', explicit: explicitUpdate}]);
  const [gateCheck, setGateCheck] = useState(null);
  const [gateDone, setGateDone] = useState(explicitUpdate);

  const screen = stack[stack.length - 1];

  const go = next => setStack(current => [...current, next]);

  const back = refresh => {
    setStack(current => {
      if (current.length <= 1) {
        return current;
      }

      return current.slice(0, -1);
    });
  };

  useEffect(() => {
    if (explicitUpdate || gateDone) {
      return;
    }

    bridge('update-check')
      .then(check => {
        setGateCheck(check);

        if (!check.available && !check.mandatory) {
          setGateDone(true);
          setStack([{name: 'root'}]);
        }
      })
      .catch(() => {
        setGateDone(true);
        setStack([{name: 'root'}]);
      });
  }, []);

  if (screen.name === 'gate') {
    if (!gateCheck) {
      return <Loading text="Opening APX…" />;
    }

    return (
      <UpdateScreen
        initial={gateCheck}
        onContinue={() => {
          setGateDone(true);
          setStack([{name: 'root'}]);
        }}
      />
    );
  }

  if (screen.name === 'update') {
    return (
      <UpdateScreen
        explicit
        onContinue={() => {
          if (stack.length > 1) {
            back();
          } else {
            setStack([{name: 'root'}]);
          }
        }}
      />
    );
  }

  if (screen.name === 'root') return <Root go={go} />;
  if (screen.name === 'devices') return <Devices go={go} back={back} />;
  if (screen.name === 'device') return <Device screen={screen} go={go} back={back} />;
  if (screen.name === 'device-details') return <DeviceDetails screen={screen} back={back} />;
  if (screen.name === 'device-nickname') return <NicknameEditor screen={screen} back={back} />;
  if (screen.name === 'device-services') return <DeviceServices screen={screen} back={back} />;
  if (screen.name === 'device-server-mode') return <DeviceServerMode screen={screen} go={go} back={back} />;

  if (screen.name === 'services') return <Services go={go} back={back} />;
  if (screen.name === 'service') return <Service screen={screen} go={go} back={back} />;
  if (screen.name === 'credentials') return <Credentials screen={screen} go={go} back={back} />;
  if (screen.name === 'credential-edit') return <CredentialEditor screen={screen} back={back} />;
  if (screen.name === 'credential-test') return <CredentialTest screen={screen} back={back} />;
  if (screen.name === 'credential-remove') return <CredentialRemove screen={screen} back={back} />;
  if (screen.name === 'service-assignments') return <ServiceAssignments screen={screen} back={back} />;
  if (screen.name === 'service-connections') return <ServiceConnections screen={screen} back={back} />;
  if (screen.name === 'service-toggle') return <ServiceToggle screen={screen} back={back} />;
  if (screen.name === 'service-settings') return <ServiceSettings screen={screen} go={go} back={back} />;

  if (screen.name === 'porkbun-domains') return <PorkbunDomains screen={screen} go={go} back={back} />;
  if (screen.name === 'porkbun-domain') return <PorkbunDomain screen={screen} go={go} back={back} />;
  if (screen.name === 'porkbun-dns') return <PorkbunDNS screen={screen} go={go} back={back} />;
  if (screen.name === 'porkbun-dns-add') return <DNSAdd screen={screen} back={back} />;
  if (screen.name === 'porkbun-dns-record') return <DNSRecord screen={screen} go={go} back={back} />;
  if (screen.name === 'porkbun-dns-delete') return <DNSDelete screen={screen} back={back} />;

  if (screen.name === 'plugins') return <Plugins go={go} back={back} />;
  if (screen.name === 'plugin') return <Plugin screen={screen} go={go} back={back} />;

  if (screen.name === 'prompts') return <Prompts go={go} back={back} />;
  if (screen.name === 'prompt-new') return <NewPrompt back={back} />;
  if (screen.name === 'prompt') return <PromptScreen screen={screen} back={back} />;

  if (screen.name === 'agents') return <Agents back={back} />;
  if (screen.name === 'shared-settings') return <SharedSettings back={back} />;
  if (screen.name === 'settings') return <OpenPowerSettings go={go} back={back} />;
  if (screen.name === 'apx-servers') return <APXServers go={go} back={back} />;
  if (screen.name === 'apx-server') return <APXServer screen={screen} go={go} back={back} />;


  if (screen.name === 'service-health') {
    const service = screen.service;
    const health = normalizeStatus(service.health || service.status || 'Available');

    return (
      <Menu
        crumb={['Services', service.name, 'Status']}
        title={service.name}
        subtitle={health?.label || 'Status unavailable'}
        items={[
          {
            id: 'test',
            label: 'Test connection',
            description: 'Verify the service is actually responding'
          },
          {
            id: 'credentials',
            label: 'Credentials',
            description: 'Manage authentication'
          },
          {
            id: 'back',
            label: 'Back'
          }
        ]}
        onSelect={item => {
          if (item.id === 'test') {
            go({name: 'credential-test', service});
          } else if (item.id === 'credentials') {
            go({name: 'credentials', service});
          } else {
            back();
          }
        }}
        onBack={back}
      />
    );
  }

  if (screen.name === 'service-about') {
    const s = screen.service;

    return (
      <DetailScreen
        crumb={['Services', s.name, 'About']}
        title={s.name}
        values={[
          ['Status', s.status],
          ['Host', s.host],
          ['Description', s.description || '—']
        ]}
        onBack={back}
      />
    );
  }

  if (screen.name === 'plugin-about') {
    const p = screen.plugin;

    return (
      <DetailScreen
        crumb={['Plugins', p.name, 'About']}
        title={p.name}
        values={[
          ['Version', p.version],
          ['Status', p.status],
          ['Description', p.description || '—']
        ]}
        onBack={back}
      />
    );
  }

  if (screen.name === 'domain-details') {
    const d = screen.data || {};

    return (
      <DetailScreen
        crumb={['Services', screen.service.name, 'Domains', screen.domain, 'Details']}
        title={screen.domain}
        values={Object.entries(d)
          .filter(([, value]) => typeof value !== 'object')
          .slice(0, 12)}
        onBack={back}
      />
    );
  }

  if (screen.name === 'record-details') {
    const r = screen.record || {};

    return (
      <DetailScreen
        crumb={['Services', screen.service.name, 'Domains', screen.domain, 'DNS', 'Details']}
        title={`${r.type || 'DNS'} ${r.name || '@'}`}
        values={[
          ['Type', r.type],
          ['Name', r.name || '@'],
          ['Value', r.content],
          ['TTL', r.ttl],
          ['Record ID', r.id]
        ]}
        onBack={back}
      />
    );
  }

  if (screen.name === 'simple-message') {
    return (
      <Message
        crumb={screen.crumb || []}
        title={screen.title}
        message={screen.message}
        onBack={back}
      />
    );
  }

  if (screen.name === 'device-link') {
    return (
      <Message
        crumb={['Devices', 'Link']}
        title="Link a device"
        message="Local discovery and OpenPower account linking use APX connection providers. Configure a provider and it will appear here automatically."
        onBack={back}
      />
    );
  }

  return <Root go={go} />;
}

if (process.argv.includes('--smoke')) {
  bridge('info')
    .then(() => process.exit(0))
    .catch(() => process.exit(1));
} else {
  render(<App />);
}
