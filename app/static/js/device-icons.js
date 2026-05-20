// UniFi device model -> icon path + display name lookups.

const ICONS = {
  'OPENWRT':   '/static/devices/openwrt-generic.svg',
  'UCGMAX':    '/static/devices/UCGMAX.avif',
  'UCGULTRA':  '/static/devices/UCG-ULTRA.avif',
  'U5GMAX':    '/static/devices/U5G_Max.avif',
  'UMBBE630':  '/static/devices/U5G_Max.avif',
  'UMR':       '/static/devices/U5G_Max.avif',
  'UMRPRO':    '/static/devices/U5G_Max.avif',
  'UDM':       '/static/devices/UDM.png',
  'UDMB':      '/static/devices/UDM.png',
  'UDMPRO':    '/static/devices/UDM.png',
  'UDMPROMAX': '/static/devices/UDM.png',
  'UDMSE':     '/static/devices/UDM-SE.png',
  'UDMPROSE':  '/static/devices/UDM-SE.png',
  'UDR':       '/static/devices/UDR.png',
  'UX':        '/static/devices/UX.avif',
  'UNIEXPRESS':'/static/devices/UX.avif',
  'UXGPRO':    '/static/devices/UXGPRO.png',
  'UXGMAX':    '/static/devices/UXGMAX.png',
};

const NAMES = {
  'OPENWRT':   'OpenWrt Router',
  'UCGMAX':    'UCG-Max',
  'UCGULTRA':  'UCG-Ultra',
  'UDM':       'Dream Machine',
  'UDMB':      'Dream Machine',
  'UDMPRO':    'Dream Machine Pro',
  'UDMPROMAX': 'Dream Machine Pro Max',
  'UDMSE':     'Dream Machine SE',
  'UDMPROSE':  'Dream Machine Pro SE',
  'UDR':       'Dream Router',
  'UX':        'UniFi Express',
  'UNIEXPRESS':'UniFi Express',
  'UXGPRO':    'Gateway Pro',
  'UXGMAX':    'Gateway Max',
  'UXGLITE':   'Gateway Lite',
  'UXGL':      'Gateway Lite',
  'UXGE':      'Gateway Enterprise',
  'USG':       'Security Gateway',
  'USG3P':     'Security Gateway 3P',
  'USGPRO4':   'Security Gateway Pro 4',
  'USG4P':     'Security Gateway Pro 4',
  'U5GMAX':    'U5G-Max',
  'UMBBE630':  'U5G-Max',
  'UMR':       'Mobile Router',
  'UMRPRO':    'Mobile Router Pro',
  'ULTE':      'U-LTE',
  'ULTEPRO':   'U-LTE Pro',
};

function _key(model) {
  return (model || '').toUpperCase().replace(/[-\s]/g, '');
}

window.deviceIcon = (model) => ICONS[_key(model)] || '';
window.fmtModel   = (model) => NAMES[_key(model)] || '';
