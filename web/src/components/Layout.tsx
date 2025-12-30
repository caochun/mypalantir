import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { 
  Squares2X2Icon, 
  CubeIcon, 
  LinkIcon,
  Bars3Icon,
  XMarkIcon,
  ChartBarIcon,
  ServerIcon
} from '@heroicons/react/24/outline';
import type { ObjectType, LinkType } from '../api/client';
import { schemaApi } from '../api/client';
import { useEffect } from 'react';

interface LayoutProps {
  children: React.ReactNode;
}

export default function Layout({ children }: LayoutProps) {
  const location = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [objectTypes, setObjectTypes] = useState<ObjectType[]>([]);
  const [linkTypes, setLinkTypes] = useState<LinkType[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadData = async () => {
      try {
        const [objectTypesData, linkTypesData] = await Promise.all([
          schemaApi.getObjectTypes(),
          schemaApi.getLinkTypes(),
        ]);
        setObjectTypes(objectTypesData);
        setLinkTypes(linkTypesData);
      } catch (error) {
        console.error('Failed to load schema:', error);
      } finally {
        setLoading(false);
      }
    };
    loadData();
  }, []);

  const isActive = (path: string) => {
    return location.pathname.startsWith(path);
  };

  return (
    <div className="flex h-screen bg-gray-50">
      {/* Sidebar */}
      <div
        className={`${
          sidebarOpen ? 'w-64' : 'w-0'
        } bg-white border-r border-gray-200 transition-all duration-300 overflow-hidden flex flex-col`}
      >
        <div className="p-4 border-b border-gray-200">
          <div className="flex items-center justify-between">
            <h1 className="text-xl font-bold text-gray-900">MyPalantir</h1>
            <button
              onClick={() => setSidebarOpen(false)}
              className="lg:hidden text-gray-500 hover:text-gray-700"
            >
              <XMarkIcon className="w-5 h-5" />
            </button>
          </div>
          <p className="text-sm text-gray-500 mt-1">Ontology Browser</p>
        </div>

        <div className="flex-1 overflow-y-auto">
          <nav className="p-2">
            <Link
              to="/schema"
              className={`flex items-center px-3 py-2 rounded-lg mb-2 ${
                isActive('/schema') && location.pathname === '/schema'
                  ? 'bg-blue-50 text-blue-700'
                  : 'text-gray-700 hover:bg-gray-100'
              }`}
            >
              <Squares2X2Icon className="w-5 h-5 mr-3" />
              Schema
            </Link>

            <Link
              to="/schema-graph"
              className={`flex items-center px-3 py-2 rounded-lg mb-2 ${
                isActive('/schema-graph')
                  ? 'bg-blue-50 text-blue-700'
                  : 'text-gray-700 hover:bg-gray-100'
              }`}
            >
              <ChartBarIcon className="w-5 h-5 mr-3" />
              Schema Graph
            </Link>

            <Link
              to="/data-sources"
              className={`flex items-center px-3 py-2 rounded-lg mb-2 ${
                isActive('/data-sources')
                  ? 'bg-blue-50 text-blue-700'
                  : 'text-gray-700 hover:bg-gray-100'
              }`}
            >
              <ServerIcon className="w-5 h-5 mr-3" />
              Data Sources
            </Link>

            {!loading && (
              <>
                <div className="mt-4 mb-2">
                  <h2 className="px-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    Object Types
                  </h2>
                </div>
                {objectTypes.map((ot) => (
                  <Link
                    key={ot.name}
                    to={`/instances/${ot.name}`}
                    className={`flex items-center px-3 py-2 rounded-lg mb-1 ${
                      isActive(`/instances/${ot.name}`)
                        ? 'bg-blue-50 text-blue-700'
                        : 'text-gray-700 hover:bg-gray-100'
                    }`}
                  >
                    <CubeIcon className="w-4 h-4 mr-3" />
                    <span className="text-sm">{ot.name}</span>
                  </Link>
                ))}

                <div className="mt-4 mb-2">
                  <h2 className="px-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    Link Types
                  </h2>
                </div>
                {linkTypes.map((lt) => (
                  <Link
                    key={lt.name}
                    to={`/links/${lt.name}`}
                    className={`flex items-center px-3 py-2 rounded-lg mb-1 ${
                      isActive(`/links/${lt.name}`)
                        ? 'bg-blue-50 text-blue-700'
                        : 'text-gray-700 hover:bg-gray-100'
                    }`}
                  >
                    <LinkIcon className="w-4 h-4 mr-3" />
                    <span className="text-sm">{lt.name}</span>
                  </Link>
                ))}
              </>
            )}
          </nav>
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top bar */}
        <header className="bg-white border-b border-gray-200 px-4 py-3 flex items-center">
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="lg:hidden text-gray-500 hover:text-gray-700 mr-3"
          >
            <Bars3Icon className="w-6 h-6" />
          </button>
          <h2 className="text-lg font-semibold text-gray-900">
            {location.pathname === '/schema' && 'Schema Browser'}
            {location.pathname.startsWith('/instances/') && 'Instances'}
            {location.pathname.startsWith('/links/') && 'Links'}
            {location.pathname.startsWith('/schema-graph') && 'Schema Graph'}
            {location.pathname.startsWith('/data-sources') && 'Data Sources'}
          </h2>
        </header>

        {/* Content area */}
        <main className={`flex-1 ${location.pathname.startsWith('/schema-graph') ? 'overflow-hidden p-0' : 'overflow-y-auto p-6'}`}>{children}</main>
      </div>
    </div>
  );
}

