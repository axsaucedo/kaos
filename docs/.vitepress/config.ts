import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'KAOS',
  description: 'K8s Agent Orchestration System',
  
  // For GitHub Pages deployment to /kaos/
  base: '/kaos/',
  
  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: '/kaos/logo.svg' }]
  ],

  // Ignore dead links for external references
  ignoreDeadLinks: true,

  themeConfig: {
    logo: '/logo.svg',
    siteTitle: 'KAOS',
    
    nav: [
      { text: 'Guide', link: '/getting-started/quickstart' },
      { text: 'Operator', link: '/operator/overview' },
      { text: 'Python', link: '/python-framework/overview' },
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
        text: 'Kubernetes Operator',
        items: [
          { text: 'Agent CRD', link: '/operator/agent-crd' },
          { text: 'ModelAPI CRD', link: '/operator/modelapi-crd' },
          { text: 'MCPServer CRD', link: '/operator/mcpserver-crd' },
          { text: 'Gateway API', link: '/operator/gateway-api' }
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
          { text: 'Environment Variables', link: '/reference/environment-variables' },
          { text: 'Troubleshooting', link: '/reference/troubleshooting' }
        ]
      },
      {
        text: 'Development',
        items: [
          { text: 'Testing', link: '/development/testing' }
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
  }
})
