import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'KAOS',
  description: 'K8s Agent Orchestration System',
  base: '/kaos/',
  
  head: [
    ['link', { rel: 'icon', href: '/kaos/favicon.ico' }]
  ],

  // Ignore dead links to external files and missing pages
  ignoreDeadLinks: [
    /\.\.\/.*/, // Ignore parent directory links
    /CLAUDE/, // Ignore CLAUDE.md links
    /REPORT/, // Ignore REPORT.md links
  ],

  themeConfig: {
    logo: '/logo.svg',
    
    nav: [
      { text: 'Guide', link: '/getting-started/quickstart' },
      { text: 'Reference', link: '/reference/environment-variables' },
      { text: 'GitHub', link: 'https://github.com/axsaucedo/kaos' }
    ],

    sidebar: {
      '/': [
        {
          text: 'Getting Started',
          collapsed: false,
          items: [
            { text: 'Quick Start', link: '/getting-started/quickstart' },
            { text: 'Installation', link: '/getting-started/installation' },
            { text: 'Concepts', link: '/getting-started/concepts' }
          ]
        },
        {
          text: 'Python Framework',
          collapsed: false,
          items: [
            { text: 'Overview', link: '/python-framework/overview' },
            { text: 'Agent', link: '/python-framework/agent' },
            { text: 'Agentic Loop', link: '/python-framework/agentic-loop' },
            { text: 'MCP Tools', link: '/python-framework/mcp-tools' },
            { text: 'Model API', link: '/python-framework/model-api' },
            { text: 'Server', link: '/python-framework/server' }
          ]
        },
        {
          text: 'Kubernetes Operator',
          collapsed: false,
          items: [
            { text: 'Overview', link: '/operator/overview' },
            { text: 'Agent CRD', link: '/operator/agent-crd' },
            { text: 'ModelAPI CRD', link: '/operator/modelapi-crd' },
            { text: 'MCPServer CRD', link: '/operator/mcpserver-crd' },
            { text: 'Gateway API', link: '/operator/gateway-api' }
          ]
        },
        {
          text: 'Tutorials',
          collapsed: true,
          items: [
            { text: 'Simple Agent with Tools', link: '/tutorials/simple-agent-tools' },
            { text: 'Multi-Agent Systems', link: '/tutorials/multi-agent' },
            { text: 'Custom MCP Tools', link: '/tutorials/custom-mcp-tools' }
          ]
        },
        {
          text: 'Reference',
          collapsed: true,
          items: [
            { text: 'Environment Variables', link: '/reference/environment-variables' },
            { text: 'Troubleshooting', link: '/reference/troubleshooting' }
          ]
        },
        {
          text: 'Development',
          collapsed: true,
          items: [
            { text: 'Testing', link: '/development/testing' }
          ]
        }
      ]
    },

    socialLinks: [
      { icon: 'github', link: 'https://github.com/axsaucedo/kaos' }
    ],

    footer: {
      message: 'Released under the Apache 2.0 License.',
      copyright: 'Copyright © 2024 KAOS Contributors'
    },

    search: {
      provider: 'local'
    },

    editLink: {
      pattern: 'https://github.com/axsaucedo/kaos/edit/main/docs/:path',
      text: 'Edit this page on GitHub'
    }
  }
})
