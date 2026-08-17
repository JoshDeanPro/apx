import React, {
  useEffect,
  useMemo,
  useState
} from 'react';

import {
  Box,
  Text,
  render,
  useApp,
  useInput
} from 'ink';

import {spawn} from 'node:child_process';

const h = React.createElement;

const ORANGE = '#ff6a00';
const MUTED = '#777777';
const DIM = '#555555';
const PYTHON = process.env.APX_PYTHON || 'python3';

const BRAND = {
  airtable: 'Airtable',
  aws: 'AWS',
  cloudflare: 'Cloudflare',
  digitalocean: 'Digital Ocean',
  discord: 'Discord',
  godaddy: 'GoDaddy',
  openai: 'OpenAI',
  paddle: 'Paddle',
  porkbun: 'Porkbun',
  purelymail: 'PurelyMail',
  supabase: 'Supabase'
};

function niceName(value) {
  const raw = String(value || '');
  const known = BRAND[raw.toLowerCase()];

  if (known) return known;

  return raw
    .replace(/[-_]+/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase());
}

function normalizeStatus(value) {
  if (!value) return null;

  if (typeof value === 'object') {
    return {
      state: String(value.state || 'neutral').toLowerCase(),
      label: String(value.label || '').trim()
    };
  }

  const label = String(value).trim();
  const low = label.toLowerCase();

  if (
    low.includes('error') ||
    low.includes('fail') ||
    low.includes('invalid') ||
    low.includes('unreachable') ||
    low.includes('denied')
  ) {
    return {state: 'failed', label};
  }

  if (
    low.includes('need') ||
    low.includes('warning') ||
    low.includes('setup') ||
    low.includes('partial') ||
    low.includes('pending') ||
    low.includes('connecting') ||
    low.includes('syncing')
  ) {
    return {state: 'attention', label};
  }

  if (
    low.includes('ready') ||
    low.includes('healthy') ||
    low.includes('connected') ||
    low.includes('online') ||
    low.includes('active') ||
    low.includes('enabled') ||
    low.includes('configured') ||
    low.includes('installed') ||
    low.includes('working') ||
    low.includes('assigned')
  ) {
    return {state: 'healthy', label};
  }

  if (
    low.includes('disabled') ||
    low.includes('inactive') ||
    low.includes('offline') ||
    low.includes('not connected') ||
    low.includes('not assigned')
  ) {
    return {state: 'inactive', label};
  }

  return {state: 'neutral', label};
}

function visualStatus(value) {
  const status = normalizeStatus(value);

  if (!status) return null;

  if (status.state === 'healthy') {
    return {
      symbol: '●',
      color: 'green',
      label: status.label || 'Ready'
    };
  }

  if (
    status.state === 'attention' ||
    status.state === 'progress'
  ) {
    return {
      symbol: '●',
      color: 'yellow',
      label: status.label || 'Needs attention'
    };
  }

  if (status.state === 'failed') {
    return {
      symbol: '●',
      color: 'red',
      label: status.label || 'Error'
    };
  }

  return {
    symbol: '○',
    color: MUTED,
    label: status.label || 'Inactive'
  };
}

function rank(item) {
  const status = normalizeStatus(item.health || item.status);

  if (item.enabled === false || status?.state === 'inactive') {
    return 4;
  }

  if (status?.state === 'healthy') return 0;
  if (status?.state === 'attention') return 1;
  if (status?.state === 'failed') return 2;
  return 3;
}

function sortOperational(items) {
  return [...items].sort((a, b) => {
    const difference = rank(a) - rank(b);

    if (difference !== 0) {
      return difference;
    }

    return niceName(a.name || '').localeCompare(
      niceName(b.name || '')
    );
  });
}

function callModule(moduleName, command, payload = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(
      PYTHON,
      ['-m', moduleName, command],
      {
        env: process.env,
        stdio: ['pipe', 'pipe', 'pipe']
      }
    );

    let stdout = '';
    let stderr = '';

    child.stdout.on('data', chunk => {
      stdout += chunk.toString();
    });

    child.stderr.on('data', chunk => {
      stderr += chunk.toString();
    });

    child.on('error', reject);

    child.on('close', code => {
      let data;

      try {
        data = JSON.parse(stdout.trim() || '{}');
      } catch {
        reject(
          new Error(
            stderr.trim() ||
            'APX returned an unreadable response.'
          )
        );
        return;
      }

      if (code !== 0 || data.ok === false) {
        reject(
          new Error(
            data.error ||
            stderr.trim() ||
            'That action could not be completed.'
          )
        );
        return;
      }

      resolve(data);
    });

    child.stdin.end(JSON.stringify(payload));
  });
}

function bridge(command, payload = {}) {
  return callModule('apx.ui_bridge', command, payload);
}

function ops(command, payload = {}) {
  return callModule('apx.ui_ops', command, payload);
}

function Header({crumb = []}) {
  return h(
    Box,
    {
      flexDirection: 'column',
      marginBottom: 1
    },
    h(
      Text,
      {
        color: ORANGE,
        bold: true
      },
      '◆ OpenPower'
    ),
    crumb.length
      ? h(
          Text,
          {color: MUTED},
          ['OpenPower', ...crumb].join('  ›  ')
        )
      : null
  );
}

function Footer({root = false}) {
  return h(
    Box,
    {marginTop: 1},
    h(
      Text,
      {color: DIM},
      root
        ? '↑↓ move   enter select   esc exit'
        : '↑↓ move   enter select   esc back'
    )
  );
}

function Spinner({text = 'Loading…', crumb = []}) {
  const frames = ['◐', '◓', '◑', '◒'];
  const [frame, setFrame] = useState(0);

  useEffect(() => {
    const timer = setInterval(
      () => setFrame(value => (value + 1) % frames.length),
      90
    );

    return () => clearInterval(timer);
  }, []);

  return h(
    Box,
    {flexDirection: 'column'},
    h(Header, {crumb}),
    h(
      Box,
      null,
      h(Text, {color: ORANGE}, `${frames[frame]} `),
      h(Text, null, text)
    )
  );
}


function ErrorView({
  crumb = [],
  error,
  back,
  exitMode = false
}) {
  const {exit} = useApp();

  const done = () => {
    if (exitMode) {
      exit();
      return;
    }

    if (back) {
      back();
    }
  };

  useInput((input, key) => {
    if (
      key.escape ||
      key.return
    ) {
      done();
    }
  });

  return h(
    Box,
    {
      flexDirection: 'column'
    },
    h(Header, {crumb}),
    h(
      Text,
      {
        color: 'red',
        bold: true
      },
      '× Something went wrong'
    ),
    h(
      Box,
      {marginTop: 1},
      h(
        Text,
        null,
        error?.message ||
          String(error)
      )
    ),
    h(
      Box,
      {marginTop: 1},
      h(
        Text,
        {color: DIM},
        exitMode
          ? 'enter or esc exit'
          : 'enter or esc back'
      )
    )
  );
}

function Message({
  crumb = [],
  title,
  message,
  back,
  exitMode = false
}) {
  const {exit} = useApp();

  const done = () => {
    if (exitMode) {
      exit();
      return;
    }

    if (back) {
      back();
    }
  };

  useInput((input, key) => {
    if (
      key.escape ||
      key.return
    ) {
      done();
    }
  });

  return h(
    Box,
    {
      flexDirection: 'column'
    },
    h(Header, {crumb}),
    h(
      Text,
      {bold: true},
      title
    ),
    message
      ? h(
          Box,
          {marginTop: 1},
          h(
            Text,
            {color: MUTED},
            message
          )
        )
      : null,
    h(
      Box,
      {marginTop: 1},
      h(
        Text,
        {color: DIM},
        exitMode
          ? 'enter or esc exit'
          : 'enter or esc back'
      )
    )
  );
}

function Menu({
  crumb = [],
  title,
  subtitle,
  items,
  select,
  back,
  root = false
}) {
  const [index, setIndex] = useState(0);
  const [help, setHelp] = useState(false);
  const {exit} = useApp();

  useEffect(() => {
    if (index >= items.length) {
      setIndex(
        Math.max(
          0,
          items.length - 1
        )
      );
    }
  }, [index, items.length]);

  useInput((input, key) => {
    const enter =
      key.return ||
      input === '\r' ||
      input === '\n';

    if (help) {
      if (
        key.escape ||
        enter ||
        input === '?'
      ) {
        setHelp(false);
      }

      return;
    }

    if (input === '?') {
      setHelp(true);
      return;
    }

    if (
      input &&
      /^[1-9]$/.test(input)
    ) {
      const target =
        Number(input) - 1;

      if (items[target]) {
        setIndex(target);
        select(items[target]);
      }

      return;
    }

    if (
      key.upArrow ||
      input === 'k'
    ) {
      setIndex(value =>
        Math.max(
          0,
          value - 1
        )
      );

      return;
    }

    if (
      key.downArrow ||
      input === 'j'
    ) {
      setIndex(value =>
        Math.min(
          items.length - 1,
          value + 1
        )
      );

      return;
    }

    if (key.home) {
      setIndex(0);
      return;
    }

    if (key.end) {
      setIndex(
        Math.max(
          0,
          items.length - 1
        )
      );

      return;
    }

    if (
      enter ||
      key.rightArrow
    ) {
      if (items[index]) {
        select(items[index]);
      }

      return;
    }

    if (key.escape) {
      if (back) {
        back();
      } else if (root) {
        exit();
      }

      return;
    }

    if (key.leftArrow) {
      if (back) {
        back();
      }
    }
  });

  if (help) {
    return h(
      Box,
      {
        flexDirection: 'column'
      },
      h(Header, {crumb}),
      h(
        Text,
        {bold: true},
        'Navigation Controls'
      ),
      h(
        Box,
        {
          flexDirection: 'column',
          marginTop: 1
        },
        h(Text, null, '↑↓  Move'),
        h(Text, null, 'Enter  Open'),
        h(Text, null, '←  Back'),
        h(Text, null, '1–9  Open item'),
        h(Text, null, '?  Help'),
        h(
          Text,
          null,
          root
            ? 'Esc  Exit'
            : 'Esc  Back'
        )
      ),
      h(
        Box,
        {marginTop: 1},
        h(
          Text,
          {color: DIM},
          'enter or esc back'
        )
      )
    );
  }

  return h(
    Box,
    {
      flexDirection: 'column'
    },
    h(Header, {crumb}),
    title
      ? h(
          Text,
          {bold: true},
          title
        )
      : null,
    subtitle
      ? h(
          Text,
          {color: MUTED},
          subtitle
        )
      : null,
    h(
      Box,
      {
        flexDirection: 'column',
        marginTop: 1
      },
      ...items.map(
        (item, itemIndex) => {
          const selected =
            itemIndex === index;

          const status =
            visualStatus(
              item.health ||
              item.status
            );

          return h(
            Box,
            {
              key:
                `${item.id}-${itemIndex}`
            },
            h(
              Text,
              {
                color:
                  selected
                    ? ORANGE
                    : DIM
              },
              selected
                ? '› '
                : '  '
            ),
            status
              ? h(
                  Text,
                  {
                    color:
                      status.color
                  },
                  `${status.symbol} `
                )
              : null,
            h(
              Text,
              {
                color:
                  selected
                    ? ORANGE
                    : undefined,
                bold: selected
              },
              item.label
            )
          );
        }
      )
    ),
    h(
      Footer,
      {root}
    )
  );
}

function LineInput({
  crumb = [],
  title,
  help,
  placeholder = '',
  initial = '',
  secret = false,
  submit,
  back
}) {
  const [value, setValue] = useState(initial);

  useInput((input, key) => {
    if (key.escape) {
      back();
      return;
    }

    if (key.return) {
      submit(value);
      return;
    }

    if (key.backspace || key.delete) {
      setValue(current => current.slice(0, -1));
      return;
    }

    if (
      input &&
      !key.ctrl &&
      !key.meta &&
      input !== '\r' &&
      input !== '\n'
    ) {
      setValue(current => current + input);
    }
  });

  const shown = secret
    ? '•'.repeat(value.length)
    : value;

  return h(
    Box,
    {flexDirection: 'column'},
    h(Header, {crumb}),
    h(Text, {bold: true}, title),
    help ? h(Text, {color: MUTED}, help) : null,
    h(
      Box,
      {marginTop: 1},
      h(Text, {color: ORANGE}, '◆ '),
      value
        ? h(Text, null, shown)
        : h(Text, {color: MUTED}, placeholder),
      h(Text, {color: MUTED}, '█')
    ),
    h(
      Box,
      {marginTop: 1},
      h(Text, {color: DIM}, 'enter save   esc back')
    )
  );
}


function SearchList({
  crumb,
  title,
  items,
  choose,
  back
}) {
  const [query, setQuery] =
    useState('');

  const [index, setIndex] =
    useState(0);

  const filtered =
    useMemo(() => {
      const needle =
        query
          .trim()
          .toLowerCase();

      if (!needle) {
        return items;
      }

      return items.filter(
        item =>
          [
            item.label,
            item.description,
            item.searchText
          ]
            .filter(Boolean)
            .join(' ')
            .toLowerCase()
            .includes(needle)
      );
    }, [items, query]);

  useEffect(() => {
    setIndex(0);
  }, [query]);

  useEffect(() => {
    if (
      index >=
      filtered.length
    ) {
      setIndex(
        Math.max(
          0,
          filtered.length - 1
        )
      );
    }
  }, [
    index,
    filtered.length
  ]);

  useInput((input, key) => {
    if (key.escape) {
      back();
      return;
    }

    if (key.upArrow) {
      setIndex(value =>
        Math.max(
          0,
          value - 1
        )
      );
      return;
    }

    if (key.downArrow) {
      setIndex(value =>
        Math.min(
          filtered.length - 1,
          value + 1
        )
      );
      return;
    }

    if (key.return) {
      if (filtered[index]) {
        choose(
          filtered[index]
        );
      }
      return;
    }

    if (
      key.backspace ||
      key.delete
    ) {
      setQuery(value =>
        value.slice(0, -1)
      );
      return;
    }

    if (
      input &&
      !key.ctrl &&
      !key.meta &&
      input !== '\r' &&
      input !== '\n'
    ) {
      setQuery(value =>
        value + input
      );
    }
  });

  return h(
    Box,
    {
      flexDirection: 'column'
    },
    h(Header, {crumb}),
    h(
      Text,
      {bold: true},
      title
    ),
    h(
      Box,
      {marginTop: 1},
      h(
        Text,
        {color: ORANGE},
        '› '
      ),
      h(
        Text,
        null,
        query
      ),
      h(
        Text,
        {color: MUTED},
        '█'
      )
    ),
    h(
      Box,
      {
        flexDirection: 'column',
        marginTop: 1
      },
      filtered.length
        ? filtered.map(
            (
              item,
              itemIndex
            ) => {
              const selected =
                itemIndex ===
                index;

              const status =
                visualStatus(
                  item.health ||
                  item.status
                );

              return h(
                Box,
                {
                  key:
                    `${item.id}-${itemIndex}`
                },
                h(
                  Text,
                  {
                    color:
                      selected
                        ? ORANGE
                        : DIM
                  },
                  selected
                    ? '› '
                    : '  '
                ),
                status
                  ? h(
                      Text,
                      {
                        color:
                          status.color
                      },
                      `${status.symbol} `
                    )
                  : null,
                h(
                  Text,
                  {
                    color:
                      selected
                        ? ORANGE
                        : undefined,
                    bold:
                      selected
                  },
                  item.label
                )
              );
            }
          )
        : h(
            Text,
            {color: MUTED},
            'No matches'
          )
    ),
    h(
      Box,
      {marginTop: 1},
      h(
        Text,
        {color: DIM},
        'type to search   ↑↓ move   enter open   esc back'
      )
    )
  );
}


function Root({go}) {
  return h(
    Menu,
    {
      root: true,
      items: [
        {
          id: 'devices',
          label: 'Devices'
        },
        {
          id: 'agents',
          label: 'Agents'
        },
        {
          id: 'prompts',
          label: 'Prompts'
        },
        {
          id: 'services',
          label: 'Services'
        },
        {
          id: 'plugins',
          label: 'Plugins'
        },
        {
          id: 'settings',
          label: 'OpenPower Settings'
        }
      ],
      select: item =>
        go({
          name: item.id
        })
    }
  );
}

function Devices({go, back}) {
  const [state, setState] = useState({
    loading: true,
    items: [],
    error: null
  });

  useEffect(() => {
    bridge('devices')
      .then(data =>
        setState({
          loading: false,
          items: data.items || [],
          error: null
        })
      )
      .catch(error =>
        setState({
          loading: false,
          items: [],
          error
        })
      );
  }, []);

  if (state.loading) {
    return h(Spinner, {
      crumb: ['Devices'],
      text: 'Finding devices…'
    });
  }

  if (state.error) {
    return h(ErrorView, {
      crumb: ['Devices'],
      error: state.error,
      back
    });
  }

  const rows = state.items.map(device => ({
    id: device.id,
    label: device.name,
    description: device.local ? 'This device' : '',
    status: device.health || device.status || 'Online',
    searchText: `${device.name} ${device.system_name || ''}`,
    device
  }));

  return h(Menu, {
    crumb: ['Devices'],
    title: 'Devices',
    back,
    items: [
      {
        id: '__search',
        label: 'Search',
        description: 'Find a device'
      },
      ...rows
    ],
    select: item => {
      if (item.id === '__search') {
        go({
          name: 'device-search',
          items: rows
        });
      } else {
        go({
          name: 'device',
          device: item.device
        });
      }
    }
  });
}

function Device({screen, go, back}) {
  const device = screen.device;

  return h(Menu, {
    crumb: ['Devices', device.name],
    title: device.name,
    subtitle: device.local ? 'This device' : device.status,
    back,
    items: [
      {
        id: 'details',
        label: 'Details',
        description: 'System and APX information'
      },
      {
        id: 'nickname',
        label: 'Nickname',
        description: device.nickname || 'Choose a friendly name'
      },
      {
        id: 'configuration',
        label: 'Configuration',
        description: 'Client, Mesh or Server'
      },
      {
        id: 'services',
        label: 'Services',
        description: 'Services this device can use'
      },
      {
        id: 'shared',
        label: 'Shared Settings',
        description: 'Portable settings and prompts'
      }
    ],
    select: item => {
      if (item.id === 'details') {
        go({name: 'device-details', device});
      } else if (item.id === 'nickname') {
        go({name: 'device-nickname', device});
      } else if (item.id === 'configuration') {
        go({name: 'device-config', device});
      } else if (item.id === 'services') {
        go({name: 'device-services', device});
      } else {
        go({name: 'shared'});
      }
    }
  });
}

function DeviceDetails({screen, back}) {
  const device = screen.device;

  const lines = [
    ['Nickname', device.nickname || 'None'],
    ['System name', device.system_name || device.id],
    ['Status', device.status || 'Online'],
    ['System', `${device.os || ''} ${device.os_version || ''}`.trim()],
    ['Architecture', device.architecture || '—'],
    ['Processor', device.processor || '—'],
    ['Memory', device.memory_gb ? `${device.memory_gb} GB` : '—'],
    ['APX', device.apx_version || '—'],
    ['Protocol', device.protocol_version || '—'],
    ['LocalCloud', device.localcloud || '—']
  ];

  useInput((input, key) => {
    if (key.escape || key.return) back();
  });

  return h(
    Box,
    {flexDirection: 'column'},
    h(Header, {
      crumb: ['Devices', device.name, 'Details']
    }),
    h(Text, {bold: true}, 'About this device'),
    h(
      Box,
      {
        flexDirection: 'column',
        marginTop: 1
      },
      ...lines.map(([label, value]) =>
        h(
          Box,
          {key: label},
          h(Text, {color: MUTED}, label.padEnd(18)),
          h(Text, null, String(value))
        )
      )
    ),
    h(
      Box,
      {marginTop: 1},
      h(Text, {color: DIM}, 'esc back')
    )
  );
}

function DeviceNickname({screen, back}) {
  const device = screen.device;
  const [working, setWorking] = useState(false);
  const [error, setError] = useState(null);

  if (working) {
    return h(Spinner, {
      crumb: ['Devices', device.name, 'Nickname'],
      text: 'Saving…'
    });
  }

  if (error) {
    return h(ErrorView, {
      crumb: ['Devices', device.name, 'Nickname'],
      error,
      back
    });
  }

  return h(LineInput, {
    crumb: ['Devices', device.name, 'Nickname'],
    title: 'Nickname',
    help: `The system name stays ${device.system_name || device.id}.`,
    placeholder: device.nickname || device.name,
    back,
    submit: async value => {
      setWorking(true);

      try {
        await bridge('nickname-set', {
          device: device.system_name || device.id,
          value
        });

        back();
      } catch (caught) {
        setWorking(false);
        setError(caught);
      }
    }
  });
}

function DeviceConfig({screen, back}) {
  const device = screen.device;

  const [state, setState] = useState({
    loading: true,
    data: null,
    error: null
  });

  const load = () => {
    ops('device-mode-get', {
      device: device.system_name || device.id
    })
      .then(data =>
        setState({
          loading: false,
          data,
          error: null
        })
      )
      .catch(error =>
        setState({
          loading: false,
          data: null,
          error
        })
      );
  };

  useEffect(load, []);

  if (state.loading) {
    return h(Spinner, {
      crumb: ['Devices', device.name, 'Configuration'],
      text: 'Loading configuration…'
    });
  }

  if (state.error) {
    return h(ErrorView, {
      crumb: ['Devices', device.name, 'Configuration'],
      error: state.error,
      back
    });
  }

  const current = state.data?.mode || 'client';

  return h(Menu, {
    crumb: ['Devices', device.name, 'Configuration'],
    title: 'Device role',
    subtitle: `Current: ${niceName(current)}`,
    back,
    items: [
      {
        id: 'server',
        label: 'Server',
        description: 'Stays ready to handle APX work for connected clients.',
        status:
          current === 'server'
            ? {state: 'healthy', label: 'Current'}
            : {state: 'inactive', label: 'Not selected'}
      },
      {
        id: 'mesh',
        label: 'Mesh',
        description: 'Connects with other APX devices and can handle shared work.',
        status:
          current === 'mesh'
            ? {state: 'healthy', label: 'Current'}
            : {state: 'inactive', label: 'Not selected'}
      },
      {
        id: 'client',
        label: 'Client',
        description: 'Uses APX services without acting as a host.',
        status:
          current === 'client'
            ? {state: 'healthy', label: 'Current'}
            : {state: 'inactive', label: 'Not selected'}
      }
    ],
    select: async item => {
      setState({
        loading: true,
        data: null,
        error: null
      });

      try {
        await ops('device-mode-set', {
          device: device.system_name || device.id,
          mode: item.id
        });

        load();
      } catch (error) {
        setState({
          loading: false,
          data: null,
          error
        });
      }
    }
  });
}

function DeviceServices({screen, back}) {
  const device = screen.device;

  const [state, setState] = useState({
    loading: true,
    services: [],
    management: null,
    error: null
  });

  const load = async () => {
    try {
      const [serviceData, managementData] = await Promise.all([
        bridge('services'),
        bridge('state')
      ]);

      setState({
        loading: false,
        services: sortOperational(serviceData.items || []),
        management: managementData.state,
        error: null
      });
    } catch (error) {
      setState({
        loading: false,
        services: [],
        management: null,
        error
      });
    }
  };

  useEffect(() => {
    load();
  }, []);

  if (state.loading) {
    return h(Spinner, {
      crumb: ['Devices', device.name, 'Services']
    });
  }

  if (state.error) {
    return h(ErrorView, {
      crumb: ['Devices', device.name, 'Services'],
      error: state.error,
      back
    });
  }

  return h(Menu, {
    crumb: ['Devices', device.name, 'Services'],
    title: 'Services',
    subtitle: 'Select a service to assign or remove it.',
    back,
    items: state.services.map(service => {
      const assigned = (
        state.management?.assignments?.[service.id] || []
      ).includes(device.id);

      return {
        id: service.id,
        label: niceName(service.name),
        description: service.description || '',
        status: assigned
          ? {state: 'healthy', label: 'Assigned'}
          : {state: 'inactive', label: 'Not assigned'},
        service
      };
    }),
    select: async item => {
      await bridge('assignment-toggle', {
        service: item.service.id,
        device: device.id
      });

      await load();
    }
  });
}

function Services({go, back}) {
  const [state, setState] = useState({
    loading: true,
    items: [],
    error: null
  });

  useEffect(() => {
    bridge('services')
      .then(data =>
        setState({
          loading: false,
          items: sortOperational(data.items || []),
          error: null
        })
      )
      .catch(error =>
        setState({
          loading: false,
          items: [],
          error
        })
      );
  }, []);

  if (state.loading) {
    return h(Spinner, {
      crumb: ['Services'],
      text: 'Finding services…'
    });
  }

  if (state.error) {
    return h(ErrorView, {
      crumb: ['Services'],
      error: state.error,
      back
    });
  }

  const rows = state.items.map(service => ({
    id: service.id,
    label: niceName(service.name),
    description: service.description || '',
    health: service.health || service.status,
    enabled: service.enabled !== false,
    searchText: `${service.name} ${service.description || ''}`,
    service
  }));

  return h(Menu, {
    crumb: ['Services'],
    title: 'Services',
    back,
    items: [
      {
        id: '__search',
        label: 'Search',
        description: 'Search services'
      },
      ...rows
    ],
    select: item => {
      if (item.id === '__search') {
        go({
          name: 'service-search',
          items: rows
        });
      } else {
        go({
          name: 'service',
          service: item.service
        });
      }
    }
  });
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
      description: 'Connect this service to another service'
    },
    {
      id: 'assignments',
      label: 'Assignments',
      description: 'Choose devices that can use this service'
    },
    {
      id: 'settings',
      label: 'Settings',
      description: 'Portable service behavior'
    },
    {
      id: 'toggle',
      label: 'Enable / Disable',
      description: 'Control whether this service can be used'
    }
  );

  return h(Menu, {
    crumb: ['Services', niceName(service.name)],
    title: niceName(service.name),
    subtitle: service.description || '',
    back,
    items,
    select: item => {
      const mapping = {
        domains: 'porkbun-domains',
        credentials: 'credentials',
        connections: 'connections',
        assignments: 'assignments',
        settings: 'service-settings',
        toggle: 'service-toggle'
      };

      go({
        name: mapping[item.id],
        service
      });
    }
  });
}

function Credentials({screen, go, back}) {
  const service = screen.service;

  const [state, setState] = useState({
    loading: true,
    fields: [],
    error: null
  });

  const load = () => {
    bridge('credential-status', {
      service: service.id
    })
      .then(data =>
        setState({
          loading: false,
          fields: data.fields || [],
          error: null
        })
      )
      .catch(error =>
        setState({
          loading: false,
          fields: [],
          error
        })
      );
  };

  useEffect(load, []);

  if (state.loading) {
    return h(Spinner, {
      crumb: ['Services', niceName(service.name), 'Credentials']
    });
  }

  if (state.error) {
    return h(ErrorView, {
      crumb: ['Services', niceName(service.name), 'Credentials'],
      error: state.error,
      back
    });
  }

  return h(Menu, {
    crumb: ['Services', niceName(service.name), 'Credentials'],
    title: 'Credentials',
    subtitle: 'Secret values stay hidden.',
    back,
    items: [
      ...state.fields.map(field => ({
        id: field.id,
        label: field.label,
        status: field.configured
          ? {state: 'healthy', label: 'Configured'}
          : {state: 'attention', label: 'Needs setup'},
        field
      })),
      {
        id: '__test',
        label: 'Test credentials',
        description: 'Check that the service accepts them'
      }
    ],
    select: item => {
      if (item.id === '__test') {
        go({
          name: 'credential-test',
          service
        });
      } else {
        go({
          name: 'credential-edit',
          service,
          field: item.field
        });
      }
    }
  });
}

function CredentialEdit({screen, back}) {
  const {service, field} = screen;
  const [working, setWorking] = useState(false);
  const [error, setError] = useState(null);

  if (working) {
    return h(Spinner, {
      crumb: ['Services', niceName(service.name), 'Credentials'],
      text: 'Saving securely…'
    });
  }

  if (error) {
    return h(ErrorView, {
      crumb: ['Services', niceName(service.name), 'Credentials'],
      error,
      back
    });
  }

  return h(LineInput, {
    crumb: ['Services', niceName(service.name), 'Credentials'],
    title: field.label,
    help: 'The value will be hidden while you type.',
    placeholder: `Enter ${field.label}`,
    secret: true,
    back,
    submit: async value => {
      if (!value) return;

      setWorking(true);

      try {
        await bridge('credential-set', {
          service: service.id,
          field: field.id,
          value
        });

        back();
      } catch (caught) {
        setWorking(false);
        setError(caught);
      }
    }
  });
}

function CredentialTest({screen, back}) {
  const service = screen.service;

  const [state, setState] = useState({
    loading: true,
    message: '',
    error: null
  });

  useEffect(() => {
    bridge('service-test', {
      service: service.id
    })
      .then(data =>
        setState({
          loading: false,
          message: data.message || 'Connection is working.',
          error: null
        })
      )
      .catch(error =>
        setState({
          loading: false,
          message: '',
          error
        })
      );
  }, []);

  if (state.loading) {
    return h(Spinner, {
      crumb: ['Services', niceName(service.name), 'Credentials'],
      text: 'Testing…'
    });
  }

  if (state.error) {
    return h(ErrorView, {
      crumb: ['Services', niceName(service.name), 'Credentials'],
      error: state.error,
      back
    });
  }

  return h(Message, {
    crumb: ['Services', niceName(service.name), 'Credentials'],
    title: '● Connected',
    message: state.message,
    back
  });
}

function Assignments({screen, back}) {
  const service = screen.service;

  const [state, setState] = useState({
    loading: true,
    devices: [],
    management: null,
    error: null
  });

  const load = async () => {
    try {
      const [devices, management] = await Promise.all([
        bridge('devices'),
        bridge('state')
      ]);

      setState({
        loading: false,
        devices: devices.items || [],
        management: management.state,
        error: null
      });
    } catch (error) {
      setState({
        loading: false,
        devices: [],
        management: null,
        error
      });
    }
  };

  useEffect(() => {
    load();
  }, []);

  if (state.loading) {
    return h(Spinner, {
      crumb: ['Services', niceName(service.name), 'Assignments']
    });
  }

  if (state.error) {
    return h(ErrorView, {
      crumb: ['Services', niceName(service.name), 'Assignments'],
      error: state.error,
      back
    });
  }

  return h(Menu, {
    crumb: ['Services', niceName(service.name), 'Assignments'],
    title: 'Where can this service be used?',
    back,
    items: state.devices.map(device => {
      const assigned = (
        state.management?.assignments?.[service.id] || []
      ).includes(device.id);

      return {
        id: device.id,
        label: device.name,
        status: assigned
          ? {state: 'healthy', label: 'Assigned'}
          : {state: 'inactive', label: 'Not assigned'},
        device
      };
    }),
    select: async item => {
      await bridge('assignment-toggle', {
        service: service.id,
        device: item.device.id
      });

      await load();
    }
  });
}

function Connections({screen, back}) {
  const service = screen.service;

  const [state, setState] = useState({
    loading: true,
    services: [],
    management: null,
    error: null
  });

  const load = async () => {
    try {
      const [services, management] = await Promise.all([
        bridge('services'),
        bridge('state')
      ]);

      setState({
        loading: false,
        services: (services.items || []).filter(
          item => item.id !== service.id
        ),
        management: management.state,
        error: null
      });
    } catch (error) {
      setState({
        loading: false,
        services: [],
        management: null,
        error
      });
    }
  };

  useEffect(() => {
    load();
  }, []);

  if (state.loading) {
    return h(Spinner, {
      crumb: ['Services', niceName(service.name), 'Connections']
    });
  }

  if (state.error) {
    return h(ErrorView, {
      crumb: ['Services', niceName(service.name), 'Connections'],
      error: state.error,
      back
    });
  }

  return h(Menu, {
    crumb: ['Services', niceName(service.name), 'Connections'],
    title: 'Connections',
    subtitle: 'Connect services so they can work together.',
    back,
    items: state.services.map(target => {
      const connected = (
        state.management?.connections || []
      ).some(
        item =>
          item.source === service.id &&
          item.target === target.id
      );

      return {
        id: target.id,
        label: niceName(target.name),
        status: connected
          ? {state: 'healthy', label: 'Connected'}
          : {state: 'inactive', label: 'Not connected'},
        target,
        connected
      };
    }),
    select: async item => {
      await bridge(
        item.connected
          ? 'connection-remove'
          : 'connection-add',
        {
          source: service.id,
          target: item.target.id
        }
      );

      await load();
    }
  });
}

function ServiceSettings({screen, back}) {
  const service = screen.service;

  return h(Menu, {
    crumb: ['Services', niceName(service.name), 'Settings'],
    title: 'Service behavior',
    back,
    items: [
      {
        id: 'best-practice',
        label: 'Best Practice',
        description: 'Use safe recommended settings'
      },
      {
        id: 'custom',
        label: 'Custom',
        description: 'Use your portable settings'
      },
      {
        id: 'manual',
        label: 'Manual',
        description: 'Ask before choosing settings'
      }
    ],
    select: async item => {
      await bridge('shared-mode', {
        mode: item.id
      });

      back();
    }
  });
}

function ServiceToggle({screen, back}) {
  const service = screen.service;

  const [state, setState] = useState({
    loading: true,
    enabled: null,
    error: null
  });

  useEffect(() => {
    bridge('service-toggle', {
      service: service.id
    })
      .then(data =>
        setState({
          loading: false,
          enabled: data.enabled,
          error: null
        })
      )
      .catch(error =>
        setState({
          loading: false,
          enabled: null,
          error
        })
      );
  }, []);

  if (state.loading) {
    return h(Spinner, {
      crumb: ['Services', niceName(service.name)],
      text: 'Updating service…'
    });
  }

  if (state.error) {
    return h(ErrorView, {
      crumb: ['Services', niceName(service.name)],
      error: state.error,
      back
    });
  }

  return h(Message, {
    crumb: ['Services', niceName(service.name)],
    title: state.enabled
      ? '● Service enabled'
      : '○ Service disabled',
    message: state.enabled
      ? 'This service can now be used.'
      : 'This service will stay out of active workflows.',
    back
  });
}

function PorkbunDomains({screen, go, back}) {
  const service = screen.service;

  const [state, setState] = useState({
    loading: true,
    items: [],
    error: null
  });

  useEffect(() => {
    bridge('porkbun-domains')
      .then(data =>
        setState({
          loading: false,
          items: data.items || [],
          error: null
        })
      )
      .catch(error =>
        setState({
          loading: false,
          items: [],
          error
        })
      );
  }, []);

  if (state.loading) {
    return h(Spinner, {
      crumb: ['Services', niceName(service.name), 'Domains'],
      text: 'Loading domains…'
    });
  }

  if (state.error) {
    return h(ErrorView, {
      crumb: ['Services', niceName(service.name), 'Domains'],
      error: state.error,
      back
    });
  }

  const rows = state.items.map(item => {
    const domain = item.domain || item.name;

    return {
      id: domain,
      label: domain,
      description: item.expireDate
        ? `Expires ${item.expireDate}`
        : '',
      domain,
      data: item
    };
  });

  return h(Menu, {
    crumb: ['Services', niceName(service.name), 'Domains'],
    title: 'Domains',
    back,
    items: [
      {
        id: '__search',
        label: 'Search',
        description: 'Search domains'
      },
      ...rows
    ],
    select: item => {
      if (item.id === '__search') {
        go({
          name: 'domain-search',
          service,
          items: rows
        });
      } else {
        go({
          name: 'porkbun-domain',
          service,
          domain: item.domain,
          data: item.data
        });
      }
    }
  });
}

function PorkbunDomain({screen, go, back}) {
  return h(Menu, {
    crumb: ['Services', niceName(screen.service.name), 'Domains', screen.domain],
    title: screen.domain,
    back,
    items: [
      {
        id: 'dns',
        label: 'DNS Records',
        description: 'View, add and remove DNS records'
      },
      {
        id: 'details',
        label: 'Details',
        description: 'Registration information'
      }
    ],
    select: item => {
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
    }
  });
}

function PorkbunDNS({screen, go, back}) {
  const [state, setState] = useState({
    loading: true,
    items: [],
    error: null
  });

  const load = () => {
    bridge('porkbun-dns', {
      domain: screen.domain
    })
      .then(data =>
        setState({
          loading: false,
          items: data.items || [],
          error: null
        })
      )
      .catch(error =>
        setState({
          loading: false,
          items: [],
          error
        })
      );
  };

  useEffect(load, []);

  if (state.loading) {
    return h(Spinner, {
      crumb: ['Services', niceName(screen.service.name), screen.domain, 'DNS']
    });
  }

  if (state.error) {
    return h(ErrorView, {
      crumb: ['Services', niceName(screen.service.name), screen.domain, 'DNS'],
      error: state.error,
      back
    });
  }

  return h(Menu, {
    crumb: ['Services', niceName(screen.service.name), screen.domain, 'DNS'],
    title: 'DNS Records',
    back,
    items: [
      {
        id: '__add',
        label: 'Add DNS Record',
        description: 'Create a new DNS record'
      },
      ...state.items.map(record => ({
        id: String(record.id),
        label: `${record.type || '?'}  ${record.name || '@'}`,
        description: record.content || '',
        record
      }))
    ],
    select: item => {
      if (item.id === '__add') {
        go({
          name: 'dns-add',
          service: screen.service,
          domain: screen.domain
        });
      } else {
        go({
          name: 'dns-record',
          service: screen.service,
          domain: screen.domain,
          record: item.record
        });
      }
    }
  });
}

function DNSAdd({screen, back}) {
  const stages = ['type', 'name', 'content', 'ttl'];

  const [stage, setStage] = useState(0);
  const [form, setForm] = useState({
    type: 'A',
    name: '',
    content: '',
    ttl: '600'
  });

  const [working, setWorking] = useState(false);
  const [error, setError] = useState(null);

  if (working) {
    return h(Spinner, {
      crumb: ['Services', niceName(screen.service.name), screen.domain, 'DNS'],
      text: 'Creating DNS record…'
    });
  }

  if (error) {
    return h(ErrorView, {
      crumb: ['Services', niceName(screen.service.name), screen.domain, 'DNS'],
      error,
      back
    });
  }

  const field = stages[stage];

  const labels = {
    type: 'Record type',
    name: 'Name or host',
    content: 'Value',
    ttl: 'TTL'
  };

  const placeholders = {
    type: 'A',
    name: '@',
    content: '1.2.3.4',
    ttl: '600'
  };

  return h(LineInput, {
    crumb: ['Services', niceName(screen.service.name), screen.domain, 'Add DNS'],
    title: labels[field],
    placeholder: placeholders[field],
    initial: form[field],
    back,
    submit: async value => {
      const next = {
        ...form,
        [field]: value
      };

      setForm(next);

      if (stage < stages.length - 1) {
        setStage(stage + 1);
        return;
      }

      setWorking(true);

      try {
        await bridge('porkbun-dns-create', {
          domain: screen.domain,
          ...next
        });

        back();
      } catch (caught) {
        setWorking(false);
        setError(caught);
      }
    }
  });
}

function DNSRecord({screen, back}) {
  const record = screen.record;
  const [working, setWorking] = useState(false);
  const [error, setError] = useState(null);

  if (working) {
    return h(Spinner, {
      crumb: ['Services', niceName(screen.service.name), screen.domain, 'DNS'],
      text: 'Deleting DNS record…'
    });
  }

  if (error) {
    return h(ErrorView, {
      crumb: ['Services', niceName(screen.service.name), screen.domain, 'DNS'],
      error,
      back
    });
  }

  return h(Menu, {
    crumb: ['Services', niceName(screen.service.name), screen.domain, 'DNS'],
    title: `${record.type || 'DNS'} ${record.name || '@'}`,
    subtitle: record.content || '',
    back,
    items: [
      {
        id: 'delete',
        label: 'Delete Record',
        description: 'Remove this DNS record'
      },
      {
        id: 'back',
        label: 'Back'
      }
    ],
    select: async item => {
      if (item.id === 'back') {
        back();
        return;
      }

      setWorking(true);

      try {
        await bridge('porkbun-dns-delete', {
          domain: screen.domain,
          id: record.id
        });

        back();
      } catch (caught) {
        setWorking(false);
        setError(caught);
      }
    }
  });
}

function Plugins({go, back}) {
  const [state, setState] = useState({
    loading: true,
    items: [],
    error: null
  });

  useEffect(() => {
    bridge('plugins')
      .then(data =>
        setState({
          loading: false,
          items: sortOperational(data.items || []),
          error: null
        })
      )
      .catch(error =>
        setState({
          loading: false,
          items: [],
          error
        })
      );
  }, []);

  if (state.loading) {
    return h(Spinner, {
      crumb: ['Plugins'],
      text: 'Finding plugins…'
    });
  }

  if (state.error) {
    return h(ErrorView, {
      crumb: ['Plugins'],
      error: state.error,
      back
    });
  }

  const rows = state.items.map(plugin => ({
    id: plugin.id,
    label: niceName(plugin.name),
    description: plugin.description || '',
    health: plugin.health || plugin.status,
    enabled: plugin.enabled !== false,
    searchText: [
      plugin.name,
      plugin.description,
      ...(Array.isArray(plugin.actions) ? plugin.actions : []),
      ...(Array.isArray(plugin.capabilities) ? plugin.capabilities : [])
    ]
      .filter(Boolean)
      .join(' '),
    plugin
  }));

  return h(Menu, {
    crumb: ['Plugins'],
    title: 'Plugins',
    back,
    items: [
      {
        id: '__search',
        label: 'Search',
        description: 'Search plugins and capabilities'
      },
      ...rows
    ],
    select: item => {
      if (item.id === '__search') {
        go({
          name: 'plugin-search',
          items: rows
        });
      } else {
        go({
          name: 'plugin',
          plugin: item.plugin
        });
      }
    }
  });
}

function Plugin({screen, go, back}) {
  const plugin = screen.plugin;

  return h(Menu, {
    crumb: ['Plugins', niceName(plugin.name)],
    title: niceName(plugin.name),
    subtitle: plugin.description || '',
    back,
    items: [
      {
        id: 'manage',
        label: 'Manage Service',
        description: 'Open the service controls'
      },
      {
        id: 'about',
        label: 'About',
        description: 'Version and capabilities'
      }
    ],
    select: item => {
      if (item.id === 'manage') {
        go({
          name: 'service',
          service: {
            id: plugin.id,
            name: plugin.name,
            description: plugin.description,
            status: plugin.status,
            health: plugin.health,
            enabled: plugin.enabled,
            raw: plugin.raw
          }
        });
      } else {
        go({
          name: 'plugin-about',
          plugin
        });
      }
    }
  });
}

function Prompts({go, back}) {
  const [state, setState] = useState({
    loading: true,
    prompts: [],
    error: null
  });

  useEffect(() => {
    bridge('state')
      .then(data =>
        setState({
          loading: false,
          prompts: data.state.prompts || [],
          error: null
        })
      )
      .catch(error =>
        setState({
          loading: false,
          prompts: [],
          error
        })
      );
  }, []);

  if (state.loading) {
    return h(Spinner, {
      crumb: ['Prompts']
    });
  }

  if (state.error) {
    return h(ErrorView, {
      crumb: ['Prompts'],
      error: state.error,
      back
    });
  }

  const rows = state.prompts.map(prompt => ({
    id: prompt.id,
    label: prompt.name,
    description: prompt.content.slice(0, 60),
    searchText: `${prompt.name} ${prompt.content}`,
    prompt
  }));

  return h(Menu, {
    crumb: ['Prompts'],
    title: 'Prompts',
    back,
    items: [
      {
        id: '__new',
        label: 'New Prompt',
        description: 'Create a portable prompt'
      },
      {
        id: '__search',
        label: 'Search',
        description: 'Search saved prompts'
      },
      ...rows
    ],
    select: item => {
      if (item.id === '__new') {
        go({name: 'prompt-new'});
      } else if (item.id === '__search') {
        go({
          name: 'prompt-search',
          items: rows
        });
      } else {
        go({
          name: 'prompt',
          prompt: item.prompt
        });
      }
    }
  });
}

function NewPrompt({back}) {
  const [name, setName] = useState('');
  const [stage, setStage] = useState('name');
  const [working, setWorking] = useState(false);
  const [error, setError] = useState(null);

  if (working) {
    return h(Spinner, {
      crumb: ['Prompts', 'New'],
      text: 'Saving prompt…'
    });
  }

  if (error) {
    return h(ErrorView, {
      crumb: ['Prompts', 'New'],
      error,
      back
    });
  }

  if (stage === 'name') {
    return h(LineInput, {
      crumb: ['Prompts', 'New'],
      title: 'Prompt name',
      placeholder: 'Deploy website',
      back,
      submit: value => {
        if (!value.trim()) return;
        setName(value.trim());
        setStage('content');
      }
    });
  }

  return h(LineInput, {
    crumb: ['Prompts', 'New'],
    title: 'Prompt',
    placeholder: 'Write the reusable instruction…',
    back: () => setStage('name'),
    submit: async content => {
      if (!content.trim()) return;

      setWorking(true);

      try {
        await bridge('prompt-add', {
          name,
          content
        });

        back();
      } catch (caught) {
        setWorking(false);
        setError(caught);
      }
    }
  });
}

function PromptView({screen, back}) {
  const prompt = screen.prompt;

  return h(Menu, {
    crumb: ['Prompts', prompt.name],
    title: prompt.name,
    subtitle: prompt.content,
    back,
    items: [
      {
        id: 'delete',
        label: 'Delete Prompt'
      },
      {
        id: 'back',
        label: 'Back'
      }
    ],
    select: async item => {
      if (item.id === 'back') {
        back();
        return;
      }

      await bridge('prompt-delete', {
        id: prompt.id
      });

      back();
    }
  });
}

function Agents({back}) {
  const [state, setState] = useState({
    loading: true,
    items: [],
    error: null
  });

  useEffect(() => {
    bridge('agents')
      .then(data =>
        setState({
          loading: false,
          items: data.items || [],
          error: null
        })
      )
      .catch(error =>
        setState({
          loading: false,
          items: [],
          error
        })
      );
  }, []);

  if (state.loading) {
    return h(Spinner, {
      crumb: ['Agents']
    });
  }

  if (state.error) {
    return h(ErrorView, {
      crumb: ['Agents'],
      error: state.error,
      back
    });
  }

  return h(Menu, {
    crumb: ['Agents'],
    title: 'Agents and clients',
    back,
    items: state.items.map(agent => ({
      id: agent.id,
      label: agent.name,
      status: agent.health || agent.status || 'Active'
    })),
    select: () => {}
  });
}

function Shared({back}) {
  const [state, setState] = useState({
    loading: true,
    mode: '',
    error: null
  });

  const load = () => {
    bridge('state')
      .then(data =>
        setState({
          loading: false,
          mode: data.state.shared?.automation_mode || 'best-practice',
          error: null
        })
      )
      .catch(error =>
        setState({
          loading: false,
          mode: '',
          error
        })
      );
  };

  useEffect(load, []);

  if (state.loading) {
    return h(Spinner, {
      crumb: ['Shared Settings']
    });
  }

  if (state.error) {
    return h(ErrorView, {
      crumb: ['Shared Settings'],
      error: state.error,
      back
    });
  }

  return h(Menu, {
    crumb: ['Shared Settings'],
    title: 'Shared behavior',
    subtitle: `Current: ${niceName(state.mode)}`,
    back,
    items: [
      {
        id: 'best-practice',
        label: 'Best Practice',
        description: 'Use safe recommended settings'
      },
      {
        id: 'custom',
        label: 'Custom',
        description: 'Use your portable settings'
      },
      {
        id: 'manual',
        label: 'Manual',
        description: 'Ask before choosing settings'
      }
    ],
    select: async item => {
      await bridge('shared-mode', {
        mode: item.id
      });

      load();
    }
  });
}

function Settings({go, back}) {
  const [background, setBackground] = useState(null);

  useEffect(() => {
    ops('background-status')
      .then(setBackground)
      .catch(() => setBackground(null));
  }, []);

  const running = Boolean(background?.enabled);

  return h(Menu, {
    crumb: ['OpenPower Settings'],
    title: 'OpenPower Settings',
    back,
    items: [
      {
        id: 'account',
        label: 'Link Account',
        description: 'Connect OpenPower.dev'
      },
      {
        id: 'shared',
        label: 'Shared Settings',
        description: 'Portable settings across devices'
      },
      {
        id: 'servers',
        label: 'Servers',
        description: 'Manage APX hosts'
      },
      {
        id: 'make-server',
        label: 'Make This an APX Server',
        description: 'Keep this device ready to handle APX work'
      },
      {
        id: 'update',
        label: 'Update APX',
        description: 'Check for a safe release'
      },
      {
        id: 'docs',
        label: 'Documentation',
        description: 'Open APX documentation'
      },
      {
        id: 'background',
        label: running
          ? 'Stop APX Background'
          : 'Start APX Background',
        description: running
          ? 'Stop background APX work'
          : 'Allow APX to keep working in the background',
        status: running
          ? {state: 'healthy', label: 'Running'}
          : {state: 'inactive', label: 'Stopped'}
      }
    ],
    select: async item => {
      if (item.id === 'account') {
        await bridge('open', {
          url: 'https://openpower.dev/sign-in'
        });
      } else if (item.id === 'shared') {
        go({name: 'shared'});
      } else if (item.id === 'servers') {
        go({name: 'devices'});
      } else if (item.id === 'make-server') {
        go({name: 'make-server'});
      } else if (item.id === 'update') {
        go({
          name: 'update',
          explicit: true
        });
      } else if (item.id === 'docs') {
        await bridge('open', {
          url: 'https://openpower.dev/apx'
        });
      } else {
        go({
          name: 'background-change',
          enabled: !running
        });
      }
    }
  });
}

function MakeServer({back}) {
  const [working, setWorking] = useState(false);
  const [error, setError] = useState(null);

  if (working) {
    return h(Spinner, {
      crumb: ['OpenPower Settings', 'APX Server'],
      text: 'Starting APX Server…'
    });
  }

  if (error) {
    return h(ErrorView, {
      crumb: ['OpenPower Settings', 'APX Server'],
      error,
      back
    });
  }

  return h(Menu, {
    crumb: ['OpenPower Settings', 'APX Server'],
    title: 'Make this device an APX Server?',
    subtitle: 'Server mode keeps APX ready in the background.',
    back,
    items: [
      {
        id: 'yes',
        label: 'Make APX Server'
      },
      {
        id: 'back',
        label: 'Back'
      }
    ],
    select: async item => {
      if (item.id === 'back') {
        back();
        return;
      }

      setWorking(true);

      try {
        await ops('device-mode-set', {
          mode: 'server'
        });

        back();
      } catch (caught) {
        setWorking(false);
        setError(caught);
      }
    }
  });
}

function BackgroundChange({screen, back}) {
  const [state, setState] = useState({
    loading: true,
    error: null
  });

  useEffect(() => {
    ops('background-set', {
      enabled: screen.enabled
    })
      .then(() =>
        setState({
          loading: false,
          error: null
        })
      )
      .catch(error =>
        setState({
          loading: false,
          error
        })
      );
  }, []);

  if (state.loading) {
    return h(Spinner, {
      crumb: ['OpenPower Settings'],
      text: screen.enabled
        ? 'Starting APX Background…'
        : 'Stopping APX Background…'
    });
  }

  if (state.error) {
    return h(ErrorView, {
      crumb: ['OpenPower Settings'],
      error: state.error,
      back
    });
  }

  return h(Message, {
    crumb: ['OpenPower Settings'],
    title: screen.enabled
      ? '● APX Background is on'
      : '○ APX Background is off',
    back
  });
}


function Update({
  screen,
  back
}) {
  const {exit} = useApp();

  const explicit =
    Boolean(
      screen?.explicit
    );

  const done = () => {
    if (explicit) {
      exit();
    } else {
      back();
    }
  };

  const [state, setState] =
    useState({
      loading: true,
      check: null,
      installing: false,
      result: null,
      error: null
    });

  useEffect(() => {
    bridge('update-check')
      .then(check =>
        setState({
          loading: false,
          check,
          installing: false,
          result: null,
          error: null
        })
      )
      .catch(error =>
        setState({
          loading: false,
          check: null,
          installing: false,
          result: null,
          error
        })
      );
  }, []);

  if (state.loading) {
    return h(
      Spinner,
      {
        crumb: ['Update'],
        text:
          'Checking for updates…'
      }
    );
  }

  if (state.installing) {
    return h(
      Spinner,
      {
        crumb: ['Update'],
        text:
          'Installing and checking update…'
      }
    );
  }

  if (state.error) {
    return h(
      ErrorView,
      {
        crumb: ['Update'],
        error: state.error,
        back: done,
        exitMode: explicit
      }
    );
  }

  if (state.result) {
    return h(
      Message,
      {
        crumb: ['Update'],
        title:
          `● APX ${state.result.version || ''} is ready`,
        message:
          'The update passed its checks.',
        exitMode: true
      }
    );
  }

  const check =
    state.check || {};

  if (
    !check.available &&
    !check.mandatory
  ) {
    return h(
      Message,
      {
        crumb: ['Update'],
        title:
          '● APX is up to date',
        message:
          `Version ${check.current || ''}`,
        back: done,
        exitMode: explicit
      }
    );
  }

  return h(
    Menu,
    {
      crumb: ['Update'],
      title:
        check.mandatory
          ? 'APX needs an update'
          : `APX ${check.latest} is available`,
      subtitle:
        check.mandatory
          ? 'This APX version is no longer supported.'
          : undefined,
      back:
        check.mandatory
          ? undefined
          : done,
      root:
        explicit &&
        check.mandatory,
      items: [
        {
          id: 'update',
          label: 'Update Now'
        },
        ...(
          check.mandatory
            ? []
            : [
                {
                  id: 'later',
                  label: 'Later'
                }
              ]
        )
      ],
      select:
        async item => {
          if (
            item.id ===
            'later'
          ) {
            done();
            return;
          }

          setState(
            current => ({
              ...current,
              installing: true
            })
          );

          try {
            const result =
              await bridge(
                'update-install',
                {
                  source_url:
                    check.source_url
                }
              );

            setState(
              current => ({
                ...current,
                installing: false,
                result
              })
            );
          } catch (error) {
            setState(
              current => ({
                ...current,
                installing: false,
                error
              })
            );
          }
        }
    }
  );
}

function SimpleDetails({screen, back}) {
  const data = screen.data || {};

  useInput((input, key) => {
    if (key.escape || key.return) back();
  });

  const entries = Object.entries(data)
    .filter(([, value]) => typeof value !== 'object')
    .slice(0, 16);

  return h(
    Box,
    {flexDirection: 'column'},
    h(Header, {crumb: screen.crumb || []}),
    h(Text, {bold: true}, screen.title),
    h(
      Box,
      {
        flexDirection: 'column',
        marginTop: 1
      },
      ...entries.map(([key, value]) =>
        h(
          Box,
          {key},
          h(Text, {color: MUTED}, `${niceName(key).padEnd(18)}`),
          h(Text, null, String(value ?? '—'))
        )
      )
    ),
    h(
      Box,
      {marginTop: 1},
      h(Text, {color: DIM}, 'esc back')
    )
  );
}

function App() {
  const args = process.argv.slice(2);
  const explicitUpdate = args[0] === 'update';

  const [stack, setStack] = useState([
    explicitUpdate
      ? {name: 'update', explicit: true}
      : {name: 'root'}
  ]);

  const screen = stack[stack.length - 1];

  const go = next => {
    setStack(current => [...current, next]);
  };

  const back = () => {
    setStack(current =>
      current.length > 1
        ? current.slice(0, -1)
        : current
    );
  };

  if (screen.name === 'root') {
    return h(Root, {go});
  }

  if (screen.name === 'devices') {
    return h(Devices, {go, back});
  }

  if (screen.name === 'device-search') {
    return h(SearchList, {
      crumb: ['Devices', 'Search'],
      title: 'Search devices',
      items: screen.items,
      back,
      choose: item =>
        go({
          name: 'device',
          device: item.device
        })
    });
  }

  if (screen.name === 'device') {
    return h(Device, {screen, go, back});
  }

  if (screen.name === 'device-details') {
    return h(DeviceDetails, {screen, back});
  }

  if (screen.name === 'device-nickname') {
    return h(DeviceNickname, {screen, back});
  }

  if (screen.name === 'device-config') {
    return h(DeviceConfig, {screen, back});
  }

  if (screen.name === 'device-services') {
    return h(DeviceServices, {screen, back});
  }

  if (screen.name === 'services') {
    return h(Services, {go, back});
  }

  if (screen.name === 'service-search') {
    return h(SearchList, {
      crumb: ['Services', 'Search'],
      title: 'Search services',
      items: screen.items,
      back,
      choose: item =>
        go({
          name: 'service',
          service: item.service
        })
    });
  }

  if (screen.name === 'service') {
    return h(Service, {screen, go, back});
  }

  if (screen.name === 'credentials') {
    return h(Credentials, {screen, go, back});
  }

  if (screen.name === 'credential-edit') {
    return h(CredentialEdit, {screen, back});
  }

  if (screen.name === 'credential-test') {
    return h(CredentialTest, {screen, back});
  }

  if (screen.name === 'assignments') {
    return h(Assignments, {screen, back});
  }

  if (screen.name === 'connections') {
    return h(Connections, {screen, back});
  }

  if (screen.name === 'service-settings') {
    return h(ServiceSettings, {screen, back});
  }

  if (screen.name === 'service-toggle') {
    return h(ServiceToggle, {screen, back});
  }

  if (screen.name === 'porkbun-domains') {
    return h(PorkbunDomains, {screen, go, back});
  }

  if (screen.name === 'domain-search') {
    return h(SearchList, {
      crumb: ['Services', niceName(screen.service.name), 'Domains', 'Search'],
      title: 'Search domains',
      items: screen.items,
      back,
      choose: item =>
        go({
          name: 'porkbun-domain',
          service: screen.service,
          domain: item.domain,
          data: item.data
        })
    });
  }

  if (screen.name === 'porkbun-domain') {
    return h(PorkbunDomain, {screen, go, back});
  }

  if (screen.name === 'porkbun-dns') {
    return h(PorkbunDNS, {screen, go, back});
  }

  if (screen.name === 'dns-add') {
    return h(DNSAdd, {screen, back});
  }

  if (screen.name === 'dns-record') {
    return h(DNSRecord, {screen, back});
  }

  if (screen.name === 'domain-details') {
    return h(SimpleDetails, {
      screen: {
        title: screen.domain,
        crumb: ['Services', niceName(screen.service.name), 'Domains', screen.domain],
        data: screen.data
      },
      back
    });
  }

  if (screen.name === 'plugins') {
    return h(Plugins, {go, back});
  }

  if (screen.name === 'plugin-search') {
    return h(SearchList, {
      crumb: ['Plugins', 'Search'],
      title: 'Search plugins',
      items: screen.items,
      back,
      choose: item =>
        go({
          name: 'plugin',
          plugin: item.plugin
        })
    });
  }

  if (screen.name === 'plugin') {
    return h(Plugin, {screen, go, back});
  }

  if (screen.name === 'plugin-about') {
    return h(SimpleDetails, {
      screen: {
        title: niceName(screen.plugin.name),
        crumb: ['Plugins', niceName(screen.plugin.name), 'About'],
        data: {
          version: screen.plugin.version,
          status: screen.plugin.status,
          description: screen.plugin.description
        }
      },
      back
    });
  }

  if (screen.name === 'prompts') {
    return h(Prompts, {go, back});
  }

  if (screen.name === 'prompt-new') {
    return h(NewPrompt, {back});
  }

  if (screen.name === 'prompt-search') {
    return h(SearchList, {
      crumb: ['Prompts', 'Search'],
      title: 'Search prompts',
      items: screen.items,
      back,
      choose: item =>
        go({
          name: 'prompt',
          prompt: item.prompt
        })
    });
  }

  if (screen.name === 'prompt') {
    return h(PromptView, {screen, back});
  }

  if (screen.name === 'agents') {
    return h(Agents, {back});
  }

  if (screen.name === 'shared') {
    return h(Shared, {back});
  }

  if (screen.name === 'settings') {
    return h(Settings, {go, back});
  }

  if (screen.name === 'make-server') {
    return h(MakeServer, {back});
  }

  if (screen.name === 'background-change') {
    return h(BackgroundChange, {screen, back});
  }

  if (screen.name === 'update') {
    return h(Update, {screen, back});
  }

  return h(Root, {go});
}

if (process.argv.includes('--smoke')) {
  Promise.all([
    bridge('info'),
    ops('background-status')
  ])
    .then(() => process.exit(0))
    .catch(error => {
      process.stderr.write(`${error.message}\n`);
      process.exit(1);
    });
} else {
  render(h(App));
}
