export type Classroom = {
  id: string;
  name: string;
  status: "available" | "reserved";
  startTime?: string;
  endTime: string;
};
