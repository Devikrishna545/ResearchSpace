import { SpaceWorkspace } from "@/features/spaces/components/space-workspace";
export default async function SpacePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <SpaceWorkspace spaceId={id} />;
}
