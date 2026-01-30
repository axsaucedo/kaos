import { defineConfig } from 'vitepress'
import { withMermaid } from 'vitepress-plugin-mermaid'

// Get version info from environment variables
// DOCS_VERSION: 'dev', '1.0.0', etc.
// DOCS_BASE: '/kaos/', '/kaos/dev/', '/kaos/v1.0.0/', etc.
const docsVersion = process.env.DOCS_VERSION || 'dev'
const docsBase = process.env.DOCS_BASE || '/kaos/'

// Parse versions list from environment (JSON array) or use defaults
function getVersionsNav() {
  const versionsJson = process.env.VERSIONS_JSON || '[]'
  try {
    const versions: string[] = JSON.parse(versionsJson)
    const items = [
      { text: 'dev', link: 'https://axsaucedo.github.io/kaos/dev/' }
    ]
    
    if (versions.length > 0) {
      // First version is latest
      items.push({ 
        text: `latest (v${versions[0]})`, 
        link: 'https://axsaucedo.github.io/kaos/latest/' 
      })
      // Add individual versions
      versions.forEach(v => {
        items.push({ text: `v${v}`, link: `https://axsaucedo.github.io/kaos/v${v}/` })
      })
    }
    
    return items
  } catch {
    return [
      { text: 'dev', link: 'https://axsaucedo.github.io/kaos/dev/' }
    ]
  }
}

export default withMermaid(defineConfig({
  title: 'KAOS',
  description: 'K8s Agent Orchestration System',
  
  // Configurable base for multi-version deployment
  base: docsBase as `/${string}/`,
  
  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: `${docsBase}logo.svg` }]
  ],

  // Ignore dead links for external references
  ignoreDeadLinks: true,

  themeConfig: {
    logo: '/logo.svg',
    siteTitle: 'KAOS',
    
    nav: [
      { text: 'Guide', link: '/getting-started/quickstart' },
      { text: 'CLI', link: '/cli/overview' },
      { text: 'UI', link: '/ui/overview' },
      { text: 'Operator', link: '/operator/overview' },
      { text: 'Python', link: '/python-framework/overview' },
      { 
        text: docsVersion === 'dev' ? 'dev' : `v${docsVersion}`,
        items: getVersionsNav()
      },
      { text: 'GitHub', link: 'https://github.com/axsaucedo/kaos' }
    ],

    sidebar: [
      {
        text: 'Getting Started',
        items: [
          { text: 'Quick Start', link: '/getting-started/quickstart' },
          { text: 'Installation', link: '/getting-started/installation' },
          { text: 'Concepts', link: '/getting-started/concepts' }
        ]
      },
      {
        text: 'CLI',
        items: [
          { text: 'Overview', link: '/cli/overview' },
          { text: 'Commands', link: '/cli/commands' }
        ]
      },
      {
        text: 'Web UI',
        items: [
          { text: 'Overview', link: '/ui/overview' },
          { text: 'Features', link: '/ui/features' }
        ]
      },
      {
        text: 'Kubernetes Operator',
        items: [
          { text: 'Agent CRD', link: '/operator/agent-crd' },
          { text: 'ModelAPI CRD', link: '/operator/modelapi-crd' },
          { text: 'MCPServer CRD', link: '/operator/mcpserver-crd' },
          { text: 'Gateway API', link: '/operator/gateway-api' },
          { text: 'OpenTelemetry', link: '/operator/telemetry' }
        ]
      },
      {
        text: 'Python Framework',
        items: [
          { text: 'Overview', link: '/python-framework/overview' },
          { 
            text: 'Agent', 
            link: '/python-framework/agent',
            items: [
              { text: 'Agent Server', link: '/python-framework/server' },
              { text: 'Agentic Loop', link: '/python-framework/agentic-loop' },
              { text: 'Memory', link: '/python-framework/memory' }
            ]
          },
          { text: 'MCP Tools', link: '/python-framework/mcp-tools' },
          { text: 'Model API Client', link: '/python-framework/model-api' }
        ]
      },
      {
        text: 'Tutorials',
        items: [
          { text: 'Simple Agent', link: '/tutorials/simple-agent-tools' },
          { text: 'Multi-Agent', link: '/tutorials/multi-agent' },
          { text: 'Custom Tools', link: '/tutorials/custom-mcp-tools' }
        ]
      },
      {
        text: 'Reference',
        items: [
          { text: 'Control Plane Overview', link: '/operator/overview' },
          { text: 'Docker Images', link: '/reference/docker-images' },
          { text: 'Environment Variables', link: '/reference/environment-variables' },
          { text: 'Troubleshooting', link: '/reference/troubleshooting' }
        ]
      },
      {
        text: 'Development',
        items: [
          { text: 'Testing', link: '/development/testing' },
          { text: 'Releasing', link: '/development/releasing' }
        ]
      }
    ],

    socialLinks: [
      { icon: 'github', link: 'https://github.com/axsaucedo/kaos' }
    ],

    footer: {
      message: 'Released under the Apache 2.0 License.',
      copyright: 'Copyright © 2024-present KAOS Contributors'
    },

    search: {
      provider: 'local'
    },

    editLink: {
      pattern: 'https://github.com/axsaucedo/kaos/edit/main/docs/:path',
      text: 'Edit this page on GitHub'
    }
  },
  
  // Mermaid configuration
  mermaid: {
    // Refer to https://mermaid.js.org/config/setup/modules/mermaidAPI.html#mermaidapi-configuration-defaults
  },
  mermaidPlugin: {
    class: 'mermaid'
  }
}))
