import type { Dispatch, SetStateAction } from "react"

type Props = {
  selectedClassroom: string;
  setSelectedClassroom: Dispatch<SetStateAction<string>>;
};

function ClassroomSelector({ selectedClassroom, setSelectedClassroom }: Props) {
  return (
    <>
      <div>ClassroomSelector</div>
      <div>{selectedClassroom}</div>
    </>
  )
}

export default ClassroomSelector
